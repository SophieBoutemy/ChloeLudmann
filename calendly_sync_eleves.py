#!/usr/bin/env python3
"""
calendly_sync_eleves.py
Crée dans la base Notion "Élèves" une fiche pour chaque invité Calendly
absent de la base (compte de Chloé Ludmann).

Pour chaque email absent : Email, Nom complet, Infos Calendly (date du
PREMIER événement réservé, formatée avec la même fonction que le pipeline
IMAP -> Notion : imap_to_notion_chloe.format_date_fr).

Usage:
    python calendly_sync_eleves.py                       # sync réelle, filtrée depuis MIN_START_TIME
    python calendly_sync_eleves.py --dry-run              # simulation, aucune écriture Notion
    python calendly_sync_eleves.py --dry-run --all-history  # simulation, tout l'historique Calendly (sans filtre de date)
"""

import base64
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_to_notion_chloe import format_date_fr  # même fonction que le pipeline mail -> Notion

CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
ELEVES_DB      = os.environ.get("NOTION_EVENTS_DATABASE_ID", "35eafa74cfc980d092d0e80644bd6be7")

CALENDLY_API = "https://api.calendly.com"
NOTION_API   = "https://api.notion.com/v1"
PARIS_TZ     = ZoneInfo("Europe/Paris")

# Ne récupère que les événements à partir de cette date (évite de parcourir
# tout l'historique du compte — des milliers d'événements passés).
MIN_START_TIME = "2026-09-01T00:00:00Z"

# Appels /invitees en parallèle (l'endpoint /scheduled_events ne renvoie pas
# l'email de l'invité — vérifié sur un échantillon réel : seuls uri, name,
# start_time, invitees_counter, etc. sont présents côté événement — donc un
# appel /invitees par événement reste incontournable pour connaître l'email).
INVITEES_WORKERS = 10

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Calendly client ─────────────────────────────────────────────────────────────

class CalendlyClient:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {CALENDLY_TOKEN}"}
        self._cooldown_until = 0.0
        self._cooldown_lock = threading.Lock()

    def _wait_for_cooldown(self) -> None:
        while True:
            with self._cooldown_lock:
                remaining = self._cooldown_until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(remaining)

    def _set_cooldown(self, seconds: float) -> None:
        with self._cooldown_lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def _request(self, url: str, params: dict = None) -> dict:
        # Cooldown partagé entre tous les threads : si un thread se prend un 429,
        # TOUS les threads attendent avant de réémettre (évite l'effet de horde
        # où chaque thread relance en même temps et se reprend un 429).
        for attempt in range(8):
            self._wait_for_cooldown()
            r = requests.get(url, headers=self.headers, params=params)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 2 ** attempt))
                self._set_cooldown(wait)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()  # 8 tentatives épuisées : remonte la dernière erreur

    def _get_all(self, url: str, params: dict = None) -> list[dict]:
        results = []
        while url:
            data = self._request(url, params)
            results.extend(data.get("collection", []))
            url = data.get("pagination", {}).get("next_page")
            params = None  # next_page est déjà une URL complète avec ses query params
        return results

    def get_user_uri(self) -> str:
        payload_b64 = CALENDLY_TOKEN.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return f"{CALENDLY_API}/users/{payload['user_uuid']}"

    def list_scheduled_events(self, user_uri: str, min_start_time: str = None) -> list[dict]:
        params = {"user": user_uri, "count": 100}
        if min_start_time:
            params["min_start_time"] = min_start_time
        return self._get_all(f"{CALENDLY_API}/scheduled_events", params)

    def list_invitees(self, event_uri: str) -> list[dict]:
        return self._get_all(f"{event_uri}/invitees", {"count": 100})


# ── Notion client ───────────────────────────────────────────────────────────────

class NotionClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        })

    def load_existing_emails(self) -> set[str]:
        emails: set[str] = set()
        cursor = None
        while True:
            body = {"start_cursor": cursor} if cursor else {}
            r = self.session.post(f"{NOTION_API}/databases/{ELEVES_DB}/query", json=body)
            r.raise_for_status()
            data = r.json()
            for page in data.get("results", []):
                title = page.get("properties", {}).get("Email", {}).get("title", [])
                if title:
                    emails.add(title[0]["plain_text"].strip().lower())
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return emails

    def create_eleve(self, email: str, nom_complet: str, infos_calendly: str) -> None:
        props = {
            "Email":         {"title": [{"text": {"content": email}}]},
            "Nom complet":   {"rich_text": [{"text": {"content": nom_complet[:2000]}}]},
            "Infos Calendly": {"rich_text": [{"text": {"content": infos_calendly[:2000]}}]},
        }
        r = self.session.post(f"{NOTION_API}/pages", json={
            "parent": {"database_id": ELEVES_DB},
            "properties": props,
        })
        r.raise_for_status()


# ── Invitees : email -> premier événement réservé ───────────────────────────────

def _parse_invitees(event: dict, invitees: list[dict]) -> list[dict]:
    start_time = event.get("start_time", "")
    parsed = []
    for inv in invitees:
        email = (inv.get("email") or "").strip()
        if not email:
            continue

        first_name = (inv.get("first_name") or "").strip()
        last_name  = (inv.get("last_name") or "").strip()
        if not first_name and not last_name:
            name_parts = (inv.get("name") or "").strip().split(" ", 1)
            first_name = name_parts[0] if name_parts else ""
            last_name  = name_parts[1] if len(name_parts) > 1 else ""

        parsed.append({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "start_time": start_time,
        })
    return parsed


def collect_first_bookings(calendly: CalendlyClient, min_start_time: str = None) -> dict[str, dict]:
    """Retourne {email_lower: {email, first_name, last_name, start_time}} en ne
    gardant que la réservation la plus ancienne par email.

    NB : l'API Calendly /scheduled_events ne renvoie pas l'email de l'invité
    au niveau événement (vérifié sur un échantillon réel) — un appel
    /invitees par événement reste donc nécessaire pour obtenir les emails.
    On réduit le coût réel en (a) sautant les événements sans invité
    (invitees_counter.total == 0) et (b) parallélisant les appels /invitees.
    """
    user_uri = calendly.get_user_uri()
    events   = calendly.list_scheduled_events(user_uri, min_start_time)
    log.info(f"Calendly : {len(events)} événement(s) trouvé(s)")

    events_to_fetch = [
        e for e in events
        if not (min_start_time and e.get("start_time", "") < min_start_time)
        and e.get("invitees_counter", {}).get("total", 1) > 0
    ]
    skipped = len(events) - len(events_to_fetch)
    if skipped:
        log.info(f"  {skipped} événement(s) sans invité ou hors période, ignorés")

    first_bookings: dict[str, dict] = {}
    lock = threading.Lock()
    done = 0
    total = len(events_to_fetch)

    def fetch(event: dict) -> list[dict]:
        return _parse_invitees(event, calendly.list_invitees(event["uri"]))

    with ThreadPoolExecutor(max_workers=INVITEES_WORKERS) as pool:
        futures = {pool.submit(fetch, event): event for event in events_to_fetch}
        for future in as_completed(futures):
            for booking in future.result():
                key = booking["email"].lower()
                with lock:
                    existing = first_bookings.get(key)
                    if existing is None or booking["start_time"] < existing["start_time"]:
                        first_bookings[key] = booking
            with lock:
                done += 1
                if done % 200 == 0:
                    log.info(f"  ... {done}/{total} événements traités")

    return first_bookings


def build_infos_calendly(start_time_iso: str) -> str:
    """Reproduit exactement la logique de imap_to_notion_chloe.py (ligne
    info_calendly = ' - '.join([...])) à partir d'un start_time Calendly (UTC)."""
    dt_local    = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00")).astimezone(PARIS_TZ)
    date_cours  = dt_local.strftime("%Y-%m-%d")
    heure_cours = dt_local.strftime("%H:%M")
    date_label  = format_date_fr(date_cours, heure_cours)
    return " - ".join(p for p in ["Calendly", "Confirmation", date_label] if p)


# ── Sync ────────────────────────────────────────────────────────────────────────

def sync(dry_run: bool = False, min_start_time: str = None) -> None:
    calendly = CalendlyClient()
    notion   = NotionClient()

    bookings        = collect_first_bookings(calendly, min_start_time)
    existing_emails = notion.load_existing_emails()
    log.info(f"Notion Élèves : {len(existing_emails)} fiche(s) existante(s)")

    created_emails: list[str] = []

    for key, booking in bookings.items():
        if key in existing_emails:
            continue

        email          = booking["email"]
        nom_complet    = f"{booking['first_name']} {booking['last_name']}".strip() or email
        infos_calendly = build_infos_calendly(booking["start_time"])

        # Log dédié "trou" : email absent de la base + date de son 1er événement,
        # pour repérer si ces trous se concentrent sur une période particulière.
        log.info(f"  TROU : {email} — événement du {booking['start_time']}")

        if dry_run:
            log.info(f"[dry-run] Créerait : {email} — {nom_complet} — {infos_calendly}")
        else:
            notion.create_eleve(email, nom_complet, infos_calendly)
            log.info(f"Fiche créée : {email} — {nom_complet} — {infos_calendly}")

        created_emails.append(email)

    log.info(f"Terminé : {len(created_emails)} fiche(s) créée(s)")
    if created_emails:
        log.info("Emails créés : " + ", ".join(created_emails))


if __name__ == "__main__":
    all_history = "--all-history" in sys.argv
    sync(
        dry_run="--dry-run" in sys.argv,
        min_start_time=None if all_history else MIN_START_TIME,
    )
