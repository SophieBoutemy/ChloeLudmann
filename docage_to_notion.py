#!/usr/bin/env python3
"""
docage_to_notion.py
Sync Docage signature transactions → Notion (Clients + Événements)

Usage:
    python docage_to_notion.py           # sync only
    python docage_to_notion.py --resend  # sync + resend contracts stuck at "Relancé"

Requires: pip install requests python-dotenv
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# ── Config ─────────────────────────────────────────────────────────────────────

load_dotenv(os.path.expanduser("~/automations/.env"))

DOCAGE_EMAIL      = os.environ["DOCAGE_EMAIL"]
DOCAGE_API_KEY    = os.environ["DOCAGE_API_KEY"]
NOTION_API_KEY    = os.environ["NOTION_API_KEY"]
NOTION_CLIENTS_DB = os.getenv("NOTION_DATABASE_ID", "345afa74cfc9802ba2b9ecfc5c197996")
NOTION_EVENTS_DB  = "35eafa74cfc980d092d0e80644bd6be7"

DOCAGE_BASE = "https://api.docage.com"
NOTION_BASE = "https://api.notion.com/v1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── TransactionStatus mapping ───────────────────────────────────────────────────
#
# Docage integer status codes (observed: 5=Signé, 6=Expiré/En attente).
# Adjust if other values appear in your account.
#
TRANSACTION_STATUS: dict[int, str] = {
    0: "En attente",
    1: "En attente",
    2: "En attente",
    3: "Relancé",
    4: "En attente",
    5: "Signé",
    6: "En attente",
}


def map_status(raw: Any) -> str:
    try:
        return TRANSACTION_STATUS.get(int(raw), "En attente")
    except (TypeError, ValueError):
        return "En attente"


def parse_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return raw[:10] if len(raw) >= 10 else None


# ── Docage client ───────────────────────────────────────────────────────────────

class DocageClient:
    """HTTP Basic auth: email + API key."""

    def __init__(self):
        self.auth    = (DOCAGE_EMAIL, DOCAGE_API_KEY)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path: str, **params) -> Any:
        r = requests.get(
            f"{DOCAGE_BASE}{path}",
            auth=self.auth, headers=self.headers,
            params=params or None,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict = None) -> Any:
        r = requests.post(
            f"{DOCAGE_BASE}{path}",
            auth=self.auth, headers=self.headers,
            json=body or {},
        )
        r.raise_for_status()
        return r.json()

    def get_all_boxes(self) -> list[dict]:
        result = self._get("/Boxes")
        return result if isinstance(result, list) else []

    def get_box_entries(self, box_id: str) -> list[dict]:
        try:
            result = self._get(f"/Boxes/BoxTransactionBatchEntries/{box_id}")
            return result if isinstance(result, list) else []
        except requests.HTTPError as e:
            if e.response.status_code in (400, 404):
                return []
            raise

    def get_contact(self, contact_id: str) -> Optional[dict]:
        try:
            return self._get(f"/Contacts/ById/{contact_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def resend_transaction(self, transaction_id: str) -> Any:
        # TODO: confirm exact resend endpoint with Docage support.
        return self._post(f"/Transactions/{transaction_id}/Send")


# ── Notion client ───────────────────────────────────────────────────────────────

class NotionClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        })

    def _get(self, path: str) -> dict:
        r = self.session.get(f"{NOTION_BASE}{path}")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = self.session.post(f"{NOTION_BASE}{path}", json=body)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, body: dict) -> dict:
        r = self.session.patch(f"{NOTION_BASE}{path}", json=body)
        r.raise_for_status()
        return r.json()

    def query_db(self, db_id: str, filter_: dict = None, cursor: str = None) -> dict:
        body: dict = {}
        if filter_:
            body["filter"] = filter_
        if cursor:
            body["start_cursor"] = cursor
        return self._post(f"/databases/{db_id}/query", body)

    def load_all_clients(self) -> dict[str, dict]:
        """Load ALL clients into a dict keyed by lowercased email."""
        clients: dict[str, dict] = {}
        cursor = None
        while True:
            res = self.query_db(NOTION_CLIENTS_DB, cursor=cursor)
            for page in res.get("results", []):
                props = page.get("properties", {})
                title_parts = props.get("Email", {}).get("title", [])
                email = title_parts[0]["plain_text"].strip().lower() if title_parts else ""
                if email:
                    clients[email] = page
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
        log.info(f"Notion: {len(clients)} clients chargés")
        return clients

    def load_all_events(self) -> dict[str, list[dict]]:
        """Load ALL events grouped by client page ID (list per client)."""
        events: dict[str, list[dict]] = {}
        cursor = None
        while True:
            res = self.query_db(NOTION_EVENTS_DB, cursor=cursor)
            for page in res.get("results", []):
                relations = page.get("properties", {}).get("Client", {}).get("relation", [])
                client_id = relations[0]["id"] if relations else ""
                if client_id:
                    events.setdefault(client_id, []).append(page)
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
        total = sum(len(v) for v in events.values())
        log.info(f"Notion: {total} événements chargés ({len(events)} clients)")
        return events

    def archive_page(self, page_id: str) -> None:
        self._patch(f"/pages/{page_id}", {"archived": True})

    def create_client(self, first_name: str, last_name: str, email: str, docage_id: str) -> dict:
        nom = f"{first_name} {last_name}".strip() or email
        return self._post("/pages", {
            "parent": {"database_id": NOTION_CLIENTS_DB},
            "properties": {
                "Email":              {"title": [{"text": {"content": email}}]},
                "Nom":                {"rich_text": [{"text": {"content": nom}}]},
                "Prénom":             {"rich_text": [{"text": {"content": first_name.strip()}}]},
                "Identifiant client": {"rich_text": [{"text": {"content": docage_id}}]},
            },
        })

    def create_event(self, props: dict) -> dict:
        return self._post("/pages", {
            "parent": {"database_id": NOTION_EVENTS_DB},
            "properties": props,
        })

    def update_event(self, page_id: str, props: dict) -> dict:
        return self._patch(f"/pages/{page_id}", {"properties": props})


# ── Event helpers ───────────────────────────────────────────────────────────────

def get_page_title(page: dict) -> str:
    parts = page.get("properties", {}).get("Titre", {}).get("title", [])
    return parts[0]["plain_text"] if parts else ""


def resolve_event(client_events: list[dict]) -> tuple[Optional[dict], list[dict]]:
    if not client_events:
        return None, []
    return client_events[0], client_events[1:]


# ── Build Notion event properties ───────────────────────────────────────────────

def build_event_props(entry: dict, first_name: str, last_name: str, client_page_id: str) -> dict:
    status_int    = entry.get("TransactionStatus", 0)
    notion_status = map_status(status_int)
    sent_date     = parse_date(entry.get("CreationDate"))
    reminder_date = parse_date(entry.get("ModificationDate")) if notion_status == "Relancé" else None
    titre         = f"{first_name} {last_name}".strip() or "Sans nom"

    props: dict = {
        "Titre":                 {"title": [{"text": {"content": titre}}]},
        "Statut contrat envoyé": {"select": {"name": notion_status}},
        "Client":                {"relation": [{"id": client_page_id}]},
    }
    if sent_date:
        props["Date contrat envoyé"] = {"date": {"start": sent_date}}
    if reminder_date:
        props["Date de relance"] = {"date": {"start": reminder_date}}

    return props


# ── Sync ────────────────────────────────────────────────────────────────────────

def sync(resend_unsigned: bool = False) -> None:
    docage = DocageClient()
    notion = NotionClient()

    # Chargement bulk upfront — garantit qu'on cherche dans TOUTES les entrées existantes
    clients_by_email  = notion.load_all_clients()    # {email_lower: page}
    events_by_client  = notion.load_all_events()     # {client_page_id: [pages]}

    boxes = docage.get_all_boxes()
    log.info(f"{len(boxes)} box(es) found in Docage")

    for box in boxes:
        box_id   = box.get("Id", "")
        box_name = box.get("Name", box_id)

        if not box_id:
            log.warning("Box without ID, skipping")
            continue

        entries = docage.get_box_entries(box_id)
        if not entries:
            log.warning(f"Box '{box_name}' — no transaction entries")
            continue

        log.info(f"Box '{box_name}' — {len(entries)} entries")

        for entry in entries:
            contact_id = entry.get("ContactId", "")
            entry_id   = entry.get("Id", "")

            if not contact_id:
                log.warning(f"  Entry {entry_id}: no ContactId, skipping")
                continue

            contact = docage.get_contact(contact_id)
            if not contact:
                log.warning(f"  Contact {contact_id} not found, skipping")
                continue

            email      = (contact.get("Email") or "").strip()
            first_name = (contact.get("FirstName") or "").strip()
            last_name  = (contact.get("LastName")  or "").strip()

            if not email:
                log.warning(f"  Contact {contact_id} has no email, skipping")
                continue

            # ── Notion client : cherche dans TOUTES les fiches existantes ────
            client_page = clients_by_email.get(email.lower())
            if client_page:
                client_page_id = client_page["id"]
                log.info(f"  Client found   : {email}")
            else:
                client_page    = notion.create_client(first_name, last_name, email, contact_id)
                client_page_id = client_page["id"]
                clients_by_email[email.lower()] = client_page
                log.info(f"  Client created : {email}")

            # ── Notion event : une seule ligne par client ──────────────────────
            titre        = f"{first_name} {last_name}".strip() or "Sans nom"
            props        = build_event_props(entry, first_name, last_name, client_page_id)
            client_evts  = events_by_client.get(client_page_id, [])
            to_keep, to_archive = resolve_event(client_evts)

            for dup in to_archive:
                notion.archive_page(dup["id"])
                log.info(f"  Doublon archivé: {get_page_title(dup)!r}")

            if to_keep:
                notion.update_event(to_keep["id"], props)
                events_by_client[client_page_id] = [to_keep]
                log.info(f"  Event updated  : {titre}")
            else:
                new_event = notion.create_event(props)
                events_by_client[client_page_id] = [new_event]
                log.info(f"  Event created  : {titre}")

            # ── Resend uniquement si statut == "En attente" ─────────────────
            transaction_id = entry.get("TransactionId", "")
            if (resend_unsigned
                    and transaction_id
                    and entry.get("CreationDate")
                    and map_status(entry.get("TransactionStatus", 0)) == "En attente"):
                log.info(f"  Resending : transaction {transaction_id} → {email}")
                try:
                    docage.resend_transaction(transaction_id)
                    log.info(f"  Resent OK : {transaction_id}")
                    # Mettre à jour le statut à "Relancé" dans Notion
                    event_page = events_by_client.get(client_page_id, [None])[0]
                    if event_page:
                        notion.update_event(event_page["id"], {
                            "Statut contrat envoyé": {"select": {"name": "Relancé"}},
                        })
                        log.info(f"  Statut → Relancé : {email}")
                except requests.HTTPError as e:
                    log.error(f"  Resend failed ({transaction_id}): {e.response.status_code} {e.response.text[:200]}")


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    resend = "--resend" in sys.argv
    if resend:
        log.info("--resend flag active: will resend contracts at status 'Relancé'")
    sync(resend_unsigned=resend)
