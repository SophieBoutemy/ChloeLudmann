#!/usr/bin/env python3
"""
recurrence_calendly/app.py
Webhook Tally VLqbG6 -> reservations recurrentes Calendly

Endpoint utilise : POST /invitees (Scheduling API, plan Standard)
Authentification : Personal Access Token (CALENDLY_TOKEN).

Chaque créneau est vérifié en temps réel via event_type_available_times.
S'il est disponible, il est réservé immédiatement quelle que soit la date.
S'il est vide et lointain (> WINDOW_DAYS), il est mis en attente dans pending.db
et réessayé quotidiennement par retry.py.
"""

import json
import logging
import os
import re
import smtplib
import sqlite3
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_FILE = os.path.expanduser("~/automations/logs/recurrence_calendly.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
SMTP_HOST      = "ssl0.ovh.net"
SMTP_PORT      = 587
SMTP_USER      = "contact@chloeludmann.fr"
SMTP_FROM      = "no-reply@chloeludmann.fr"
SMTP_PASS      = os.environ["IMAP_PASSWORD"]
CHLOE_EMAIL    = "contact@chloeludmann.fr"

# Seuil utilisé pour classifier une réponse API vide : si le créneau est au-delà
# de WINDOW_DAYS, on suppose que la fenêtre Calendly n'est pas encore ouverte → pending.
# Si en deçà et API vide → vraiment indisponible.
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "58"))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending.db")

CALENDLY_HEADERS = {
    "Authorization": f"Bearer {CALENDLY_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; automations-chloe/1.0)",
}

EVENT_TYPES = {
    "cours de chant reguliers (30min)": {
        "uri":      "https://api.calendly.com/event_types/002e1ab4-d6dc-478e-838a-f37f704265b2",
        "location": {"kind": "physical", "location": "6 rue Desaix - 35000 Rennes"},
    },
    "cours de chant reguliers (1h)": {
        "uri":      "https://api.calendly.com/event_types/d0fd7934-6166-4adb-a12e-dca0df39983b",
        "location": {"kind": "physical", "location": "6 rue Desaix - 35000 Rennes"},
    },
    "cours de chant reguliers (1h30)": {
        "uri":      "https://api.calendly.com/event_types/26cfd098-a689-4846-8944-a1200bd88b6e",
        "location": {"kind": "physical", "location": "6 rue Desaix - 35000 Rennes"},
    },
    "cours de chant reguliers (2h)": {
        "uri":      "https://api.calendly.com/event_types/65f2bf63-5d8f-49df-a0bd-acc36f81e175",
        "location": {"kind": "physical", "location": "6 rue Desaix - 35000 Rennes"},
    },
}

JOURS_FR = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}
JOURS_FR_INV = {v: k for k, v in JOURS_FR.items()}

FREQ_HEBDO   = "hebdomadaire"
FREQ_PAIRE   = "paire"
FREQ_IMPAIRE = "impaire"
FREQ_LABELS  = {
    FREQ_HEBDO:   "Toutes les semaines",
    FREQ_PAIRE:   "Une semaine sur deux (semaine paire)",
    FREQ_IMPAIRE: "Une semaine sur deux (semaine impaire)",
}

MOIS_FR = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}


# ── Templates email — Charte graphique Chloé Ludmann ────────────────────────

LOGO_URL = "https://chloeludmann.fr/wp-content/uploads/logo-vert-bordsbeiges.png"

EMAIL_WRAPPER_OPEN = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#F8EFE2;font-family:'Roboto',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F8EFE2;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#FFFFFF;border-radius:16px;overflow:hidden;max-width:600px;">
<tr>
<td style="background-color:#23242C;padding:24px 32px;text-align:center;">
<img src="{logo_url}" alt="Chloé Ludmann" style="height:48px;margin-bottom:8px;">
</td>
</tr>
"""

EMAIL_WRAPPER_CLOSE = """<tr>
<td style="background-color:#F8EFE2;padding:20px 32px;text-align:center;">
<p style="margin:0;font-family:'Fredoka',Arial,sans-serif;color:#419958;font-size:16px;font-weight:600;">
Chloé Ludmann — Osez votre voix !
</p>
<p style="margin:6px 0 0;font-size:12px;color:#23242C;">
6 rue Desaix - 35000 Rennes
</p>
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def build_email_client(prenom_affiche, type_cours, jour_nom, heure_str, freq_label,
                       date_debut, date_fin, reserves, en_attente, indisponibles):
    html = EMAIL_WRAPPER_OPEN.format(logo_url=LOGO_URL)
    html += f"""
<tr><td style="padding:32px;">
<h1 style="font-family:'Fredoka',Arial,sans-serif;color:#EA4F26;font-size:24px;margin:0 0 16px;">
Bonjour {prenom_affiche} !
</h1>
<p style="font-size:15px;color:#23242C;line-height:1.6;margin:0 0 24px;">
Voici la confirmation de tes réservations pour <strong>{type_cours}</strong>,
le <strong>{jour_nom}</strong> à <strong>{heure_str}</strong> ({freq_label}),
du <strong>{date_debut}</strong> au <strong>{date_fin}</strong>.
</p>
</td></tr>
"""
    if reserves:
        rows = "".join(
            f"""<tr><td style="padding:10px 16px;background-color:#EAF5EC;border-radius:8px;border-bottom:1px solid #FFFFFF;">
<span style="font-size:14px;color:#23242C;">{r['date']} — {r['jour_nom']} {r['heure_str']}</span><br>
<a href="{r['ru']}" style="font-size:12px;color:#419958;text-decoration:none;font-weight:600;">↻ Déplacer</a>
&nbsp;&nbsp;
<a href="{r['cu']}" style="font-size:12px;color:#EA4F26;text-decoration:none;font-weight:600;">✕ Annuler</a>
</td></tr>
""" for r in reserves
        )
        html += f"""
<tr><td style="padding:0 32px;">
<h2 style="font-family:'Fredoka',Arial,sans-serif;color:#419958;font-size:18px;margin:0 0 12px;">
✓ Cours réservés ({len(reserves)})
</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
{rows}
</table>
</td></tr>
"""
    if en_attente:
        rows = "".join(
            f"""<tr><td style="padding:10px 16px;background-color:#FFF3E0;border-radius:8px;border-bottom:1px solid #FFFFFF;">
<span style="font-size:14px;color:#23242C;">{e['date']} — {e['jour_nom']} {e['heure_str']}</span>
</td></tr>
""" for e in en_attente
        )
        html += f"""
<tr><td style="padding:0 32px;">
<h2 style="font-family:'Fredoka',Arial,sans-serif;color:#C07000;font-size:18px;margin:0 0 12px;">
⏳ En attente de confirmation ({len(en_attente)})
</h2>
<p style="font-size:13px;color:#23242C;margin:0 0 12px;">
Ces créneaux ne sont pas encore ouverts dans l'agenda de Chloé. Une réservation automatique sera tentée dès qu'ils seront disponibles.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
{rows}
</table>
</td></tr>
"""
    if indisponibles:
        rows = "".join(
            f"""<tr><td style="padding:10px 16px;background-color:#FBEAEA;border-bottom:1px solid #FFFFFF;">
<span style="font-size:14px;color:#23242C;">{i['date']} — {i['heure_str']}</span>
</td></tr>
""" for i in indisponibles
        )
        html += f"""
<tr><td style="padding:0 32px;">
<h2 style="font-family:'Fredoka',Arial,sans-serif;color:#EA4F26;font-size:18px;margin:0 0 12px;">
✕ Non disponibles ({len(indisponibles)})
</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
{rows}
</table>
</td></tr>
"""
    html += """
<tr><td style="padding:0 32px 24px;">
<p style="font-size:13px;color:#666;line-height:1.5;margin:0;">
Tout cours annulé moins de 48h à l'avance est dû. Pense à utiliser le lien "Déplacer" si tu as besoin de changer un horaire plus de 48h avant.
</p>
</td></tr>
"""
    html += EMAIL_WRAPPER_CLOSE
    return html


def build_email_chloe(nom, email, type_cours, jour_nom, heure_str, freq_label,
                      date_debut, date_fin, reserves, en_attente, indisponibles, erreurs):
    html = EMAIL_WRAPPER_OPEN.format(logo_url=LOGO_URL)
    html += f"""
<tr><td style="padding:32px;">
<h1 style="font-family:'Fredoka',Arial,sans-serif;color:#419958;font-size:22px;margin:0 0 16px;">
Nouvelle demande récurrente
</h1>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#23242C;margin-bottom:20px;">
<tr><td style="padding:4px 0;"><strong>Élève :</strong></td><td style="padding:4px 0;">{nom}</td></tr>
<tr><td style="padding:4px 0;"><strong>Email :</strong></td><td style="padding:4px 0;">{email}</td></tr>
<tr><td style="padding:4px 0;"><strong>Cours :</strong></td><td style="padding:4px 0;">{type_cours}</td></tr>
<tr><td style="padding:4px 0;"><strong>Créneau :</strong></td><td style="padding:4px 0;">{jour_nom} {heure_str} — {freq_label}</td></tr>
<tr><td style="padding:4px 0;"><strong>Période :</strong></td><td style="padding:4px 0;">{date_debut} → {date_fin}</td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
<tr>
<td align="center" style="background-color:#EAF5EC;border-radius:8px;padding:12px;width:25%;">
<span style="font-size:20px;font-weight:700;color:#419958;">{len(reserves)}</span><br>
<span style="font-size:11px;color:#23242C;">réservés</span>
</td>
<td width="8"></td>
<td align="center" style="background-color:#FFF3E0;border-radius:8px;padding:12px;width:25%;">
<span style="font-size:20px;font-weight:700;color:#C07000;">{len(en_attente)}</span><br>
<span style="font-size:11px;color:#23242C;">en attente</span>
</td>
<td width="8"></td>
<td align="center" style="background-color:#FBEAEA;border-radius:8px;padding:12px;width:25%;">
<span style="font-size:20px;font-weight:700;color:#EA4F26;">{len(indisponibles)}</span><br>
<span style="font-size:11px;color:#23242C;">indispo.</span>
</td>
<td width="8"></td>
<td align="center" style="background-color:#FFB7DD;border-radius:8px;padding:12px;width:25%;">
<span style="font-size:20px;font-weight:700;color:#23242C;">{len(erreurs)}</span><br>
<span style="font-size:11px;color:#23242C;">erreurs</span>
</td>
</tr>
</table>
</td></tr>
"""

    def _block(title, color, bg, items, line_fn):
        if not items:
            return ""
        rows = "".join(
            f'<tr><td style="padding:6px 12px;background-color:{bg};font-size:13px;color:#23242C;border-bottom:1px solid #FFFFFF;">{line_fn(i)}</td></tr>'
            for i in items
        )
        return (f'<tr><td style="padding:0 32px;">'
                f'<h2 style="font-family:\'Fredoka\',Arial,sans-serif;color:{color};font-size:15px;margin:0 0 8px;">{title}</h2>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">{rows}</table>'
                f'</td></tr>\n')

    html += _block("Réservés", "#419958", "#EAF5EC", reserves,
                   lambda r: f"{r['date']} — {r['jour_nom']} {r['heure_str']}")
    html += _block("En attente", "#C07000", "#FFF3E0", en_attente,
                   lambda e: f"{e['date']} — {e['jour_nom']} {e['heure_str']}")
    html += _block("Indisponibles", "#EA4F26", "#FBEAEA", indisponibles,
                   lambda i: f"{i['date']} — {i['heure_str']}")
    if erreurs:
        html += _block("Erreurs", "#23242C", "#FFB7DD", erreurs,
                       lambda e: f"{e.get('date', '?')} — {e.get('r', 'erreur inconnue')}")
    html += EMAIL_WRAPPER_CLOSE
    return html


app = Flask(__name__)


# ── Base de données (réservations en attente) ─────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nom            TEXT NOT NULL,
            prenom_affiche TEXT NOT NULL,
            email          TEXT NOT NULL,
            event_type_uri TEXT NOT NULL,
            location_json  TEXT NOT NULL,
            dt_utc         TEXT NOT NULL,
            heure_str      TEXT NOT NULL,
            type_cours     TEXT NOT NULL,
            jour_nom       TEXT NOT NULL,
            frequence      TEXT NOT NULL DEFAULT 'hebdomadaire',
            created_at     TEXT NOT NULL,
            retry_count    INTEGER DEFAULT 0,
            last_retry     TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE pending ADD COLUMN frequence TEXT NOT NULL DEFAULT 'hebdomadaire'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def save_pending(nom, prenom_affiche, email, event_type_uri, location,
                 dt_utc, heure_str, type_cours, jour_nom, frequence=FREQ_HEBDO):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO pending
           (nom, prenom_affiche, email, event_type_uri, location_json,
            dt_utc, heure_str, type_cours, jour_nom, frequence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nom, prenom_affiche, email, event_type_uri, json.dumps(location),
         dt_utc.strftime("%Y-%m-%dT%H:%M:%S"), heure_str, type_cours, jour_nom, frequence,
         datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")),
    )
    conn.commit()
    conn.close()


init_db()


# ── Normalisation event type ───────────────────────────────────────────────────

def _normalize_et(s):
    """Minuscules, sans accents, sans ponctuation — pour matcher malgré les typos."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

def calendly_get(url):
    req  = urllib.request.Request(url, headers=CALENDLY_HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def calendly_post(url, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=CALENDLY_HEADERS, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode(errors="replace"))


# ── Parsing ───────────────────────────────────────────────────────────────────

def resolve_option_text(value, options):
    """Résout l'UUID Tally d'un champ à choix en texte lisible."""
    if not options:
        return None
    id_to_text = {o.get("id"): o.get("text", "") for o in options if isinstance(o, dict)}
    if isinstance(value, str):
        return id_to_text.get(value)
    if isinstance(value, list):
        texts = [id_to_text.get(v, str(v)) for v in value]
        return texts[0] if texts else None
    return None


def parse_tally_fields(fields):
    data = {}
    for f in fields:
        label   = (f.get("label") or "").lower().strip()
        value   = f.get("value", "")
        options = f.get("options", [])
        if value is None:
            value = ""
        resolved = resolve_option_text(value, options)
        if resolved is not None:
            value = resolved
        elif isinstance(value, list):
            texts = []
            for item in value:
                if isinstance(item, dict):
                    texts.append(item.get("text", str(item)))
                else:
                    texts.append(str(item))
            value = texts[0] if texts else ""
        data[label] = str(value).strip()
    return data


def resolve_field(data, *candidates):
    for key in candidates:
        if data.get(key):
            return data[key]
    for key in candidates:
        for k, v in data.items():
            if key in k and v:
                return v
    return ""


def parse_heure(s):
    s = s.strip().lower().replace(" ", "")
    if "h" in s:
        parts = s.split("h")
        return int(parts[0]), (int(parts[1]) if parts[1].isdigit() else 0)
    if ":" in s:
        parts = s.split(":")
        return int(parts[0]), (int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0)
    return int(s), 0


def parse_date_fr(s):
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    parts = s.lower().replace("er", "").replace("ème", "").split()
    if len(parts) == 3:
        try:
            m = MOIS_FR.get(parts[1], 0)
            if m:
                return date(int(parts[2]), m, int(parts[0]))
        except (ValueError, TypeError):
            pass
    raise ValueError(f"Format de date non reconnu : {s!r}")


def is_dst(d: date) -> bool:
    def last_sunday(year, month):
        day = date(year, month, 28)
        while day.weekday() != 6:
            day += timedelta(days=1)
        return day
    return last_sunday(d.year, 3) <= d < last_sunday(d.year, 10)


def local_to_utc(d: date, h: int, m: int) -> datetime:
    offset = timedelta(hours=2 if is_dst(d) else 1)
    return datetime(d.year, d.month, d.day, h, m, 0) - offset


def calc_occurrences(weekday, h, m, date_debut, date_fin, frequence=FREQ_HEBDO):
    delta   = (weekday - date_debut.weekday()) % 7
    current = date_debut + timedelta(days=delta)
    result  = []
    while current <= date_fin:
        if frequence == FREQ_HEBDO:
            result.append((current, local_to_utc(current, h, m)))
        else:
            iso_week = current.isocalendar()[1]
            if frequence == FREQ_PAIRE and iso_week % 2 == 0:
                result.append((current, local_to_utc(current, h, m)))
            elif frequence == FREQ_IMPAIRE and iso_week % 2 == 1:
                result.append((current, local_to_utc(current, h, m)))
        current += timedelta(weeks=1)
    return result


def first_valid_occurrence(weekday, date_debut, frequence):
    """Première date >= date_debut correspondant au bon jour ET à la bonne parité."""
    delta     = (weekday - date_debut.weekday()) % 7
    candidate = date_debut + timedelta(days=delta)
    if frequence == FREQ_HEBDO:
        return candidate
    while True:
        iso_week = candidate.isocalendar()[1]
        if frequence == FREQ_PAIRE and iso_week % 2 == 0:
            return candidate
        if frequence == FREQ_IMPAIRE and iso_week % 2 == 1:
            return candidate
        candidate += timedelta(weeks=1)


# ── Logique Calendly ──────────────────────────────────────────────────────────

def is_beyond_window(dt_utc: datetime) -> bool:
    return dt_utc.date() > date.today() + timedelta(days=WINDOW_DAYS)


def is_slot_available(event_type_uri: str, dt_utc: datetime) -> bool:
    start  = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    end    = (dt_utc + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    target = dt_utc.strftime("%Y-%m-%dT%H:%M")
    url = (
        "https://api.calendly.com/event_type_available_times"
        f"?event_type={urllib.parse.quote(event_type_uri, safe='')}"
        f"&start_time={urllib.parse.quote(start, safe='')}"
        f"&end_time={urllib.parse.quote(end, safe='')}"
    )
    try:
        data = calendly_get(url)
        return any(
            s.get("status") == "available" and s.get("start_time", "").startswith(target)
            for s in data.get("collection", [])
        )
    except Exception as e:
        log.warning(f"Erreur available_times {dt_utc}: {e}")
        return False


def book_slot(event_type_uri: str, location: dict, dt_utc: datetime,
              name: str, email: str) -> tuple[bool, str]:
    payload = {
        "event_type": event_type_uri,
        "start_time": dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "invitee": {
            "name":     name,
            "email":    email,
            "timezone": "Europe/Paris",
        },
        "location": location,
    }
    code, resp = calendly_post("https://api.calendly.com/invitees", payload)
    if code in (200, 201):
        resource     = resp.get("resource", {})
        uri          = resource.get("uri", "")
        cancel_url   = resource.get("cancel_url", "")
        reschedule_url = resource.get("reschedule_url", "")
        log.info(f"  ✓ Réservé : {dt_utc} → {uri}")
        return True, {"uri": uri, "cancel_url": cancel_url, "reschedule_url": reschedule_url}
    details = resp.get("details", [])
    codes   = [d.get("code", "") for d in details]
    if "already_filled" in codes:
        log.info(f"  ✗ Slot déjà pris (already_filled) : {dt_utc}")
        return False, "already_filled"
    log.warning(f"  ✗ Erreur booking {code} pour {dt_utc}: {json.dumps(resp)[:300]}")
    return False, f"erreur_{code}"


def check_and_book(event_type_uri: str, location: dict, dt_utc: datetime,
                   name: str, email: str) -> tuple[str, str]:
    """
    Retourne (statut, detail) :
      "booked"      → réservé avec succès
      "pending"     → Calendly renvoie collection vide ET créneau lointain (fenêtre pas encore ouverte)
      "unavailable" → Calendly renvoie collection vide dans la fenêtre (vraiment pris/bloqué)
      "error"       → erreur inattendue

    On appelle TOUJOURS l'API en premier. is_beyond_window() sert uniquement à
    classifier la réponse vide, jamais à court-circuiter l'appel.
    """
    available = is_slot_available(event_type_uri, dt_utc)

    if available:
        ok, detail = book_slot(event_type_uri, location, dt_utc, name, email)
        if ok:
            return "booked", detail
        if detail == "already_filled":
            return "unavailable", "créneau déjà réservé"
        return "error", detail

    # Calendly renvoie collection vide — est-ce parce que la fenêtre n'est pas ouverte ?
    if is_beyond_window(dt_utc):
        log.info(f"  ⏳ API vide + hors fenêtre estimée — en attente : {dt_utc}")
        return "pending", "hors fenêtre Calendly"

    log.info(f"  ○ Indisponible (API vide dans la fenêtre) : {dt_utc}")
    return "unavailable", "hors plage ou déjà pris"


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, html_body, cc=None):
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = to_addr
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_FROM, [to_addr] + ([cc] if cc else []), msg.as_string())


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.route("/recurrence-webhook", methods=["POST"])
def tally_webhook():
    body = request.get_json(silent=True) or {}

    if body.get("eventType") != "FORM_RESPONSE":
        log.info(f"Événement ignoré : {body.get('eventType')}")
        return jsonify({"status": "ignored"}), 200

    fields = body.get("data", {}).get("fields", [])
    log.info(f"Payload Tally brut — {len(fields)} champ(s) : "
             + json.dumps([{"label": f.get("label"), "type": f.get("type"),
                            "value": f.get("value"),
                            "options_count": len(f.get("options", []))}
                           for f in fields], ensure_ascii=False))
    d = parse_tally_fields(fields)
    log.info(f"Soumission Tally — champs résolus : {d}")

    # ── Extraction ──────────────────────────────────────────────────────────
    _prenom   = d.get("prénom", d.get("prenom", ""))
    _nom_seul = resolve_field(d, "nom", "nom complet")
    if _prenom and _nom_seul:
        nom = f"{_prenom} {_nom_seul}"
    elif _prenom:
        nom = _prenom
    else:
        nom = _nom_seul or resolve_field(d, "prénom et nom", "prenom et nom")

    prenom_affiche = _prenom if _prenom else nom

    email      = resolve_field(d, "email", "e-mail", "adresse email", "adresse e-mail")
    type_cours = resolve_field(d, "type de cours", "type de cours de chant",
                               "type de cours souhaité", "cours")
    jour_str   = resolve_field(d, "jour de la semaine", "jour de la semaine souhaité",
                               "jour souhaité", "jour").lower().strip()
    heure_str  = resolve_field(d, "heure", "heure souhaitée", "horaire").strip()
    debut_str    = resolve_field(d, "date de début", "date de début de la période",
                                 "date de debut", "date de debut de la periode", "début", "debut")
    fin_str      = resolve_field(d, "date de fin", "date de fin de la période",
                                 "date de fin de la periode", "fin", "date fin")
    frequence_str = resolve_field(d, "fréquence", "frequence", "fréquence de cours",
                                  "fréquence des cours", "type de semaines").lower().strip()
    if "impaire" in frequence_str:
        frequence = FREQ_IMPAIRE
    elif "paire" in frequence_str:
        frequence = FREQ_PAIRE
    else:
        frequence = FREQ_HEBDO
    freq_label = FREQ_LABELS[frequence]

    if not all([nom, email, type_cours, jour_str, heure_str, debut_str, fin_str]):
        missing = [k for k, v in {"nom": nom, "email": email, "type_cours": type_cours,
                                   "jour": jour_str, "heure": heure_str,
                                   "debut": debut_str, "fin": fin_str}.items() if not v]
        log.warning(f"Champs manquants {missing} — dict reçu : {d}")
        return jsonify({"status": "error", "reason": f"missing fields: {missing}"}), 400

    # ── Résolution event type ────────────────────────────────────────────────
    needle    = _normalize_et(type_cours)
    et_config = None
    for k, cfg in EVENT_TYPES.items():
        if _normalize_et(k) == needle:
            et_config = cfg
            break
    if not et_config:
        for k, cfg in EVENT_TYPES.items():
            nk = _normalize_et(k)
            if needle in nk or nk in needle:
                et_config = cfg
                break
    if not et_config:
        log.warning(f"Event type non reconnu : {type_cours!r} (normalisé: {needle!r})")
        return jsonify({"status": "error", "reason": f"event type inconnu: {type_cours}"}), 400

    event_type_uri = et_config["uri"]
    location       = et_config["location"]

    # ── Jour ────────────────────────────────────────────────────────────────
    weekday = JOURS_FR.get(jour_str)
    if weekday is None:
        for j, idx in JOURS_FR.items():
            if jour_str.startswith(j[:4]) or j.startswith(jour_str[:4]):
                weekday = idx
                break
    if weekday is None:
        log.warning(f"Jour non reconnu : {jour_str!r}")
        return jsonify({"status": "error", "reason": f"jour inconnu: {jour_str}"}), 400

    # ── Heure ───────────────────────────────────────────────────────────────
    try:
        h, m = parse_heure(heure_str)
    except Exception as e:
        log.warning(f"Heure invalide {heure_str!r}: {e}")
        return jsonify({"status": "error", "reason": f"heure invalide: {heure_str}"}), 400

    # ── Dates ───────────────────────────────────────────────────────────────
    try:
        date_debut = parse_date_fr(debut_str)
        date_fin   = parse_date_fr(fin_str)
    except ValueError as e:
        log.warning(str(e))
        return jsonify({"status": "error", "reason": str(e)}), 400

    if date_fin < date_debut:
        return jsonify({"status": "error", "reason": "date_fin < date_debut"}), 400

    # ── Occurrences ─────────────────────────────────────────────────────────
    occurrences = calc_occurrences(weekday, h, m, date_debut, date_fin, frequence)
    jour_nom    = JOURS_FR_INV[weekday].capitalize()
    log.info(
        f"{len(occurrences)} occurrence(s) — {nom} / {type_cours} / "
        f"{jour_nom} {heure_str} / {date_debut} → {date_fin} / {freq_label}"
    )

    # La période ne contient aucun jour correspondant au weekday demandé (ou à la parité)
    if not occurrences:
        first_valid = first_valid_occurrence(weekday, date_debut, frequence)
        parite_msg  = (
            f" avec la fréquence « {freq_label} »"
            if frequence != FREQ_HEBDO else ""
        )
        log.warning(
            f"Aucune occurrence : aucun {jour_nom}{parite_msg} dans {date_debut} → {date_fin}. "
            f"Prochaine occurrence valide : {first_valid}"
        )
        html_no_occ = f"""
<html><body style="font-family:sans-serif;color:#222;max-width:620px;margin:0 auto;padding:24px">
<p>Bonjour {prenom_affiche},</p>
<p>Votre demande de <strong>{type_cours}</strong> le <strong>{jour_nom}</strong>
   à <strong>{heure_str}</strong> (<em>{freq_label}</em>) n'a pas pu être traitée :
   la période choisie
   (du <strong>{date_debut.strftime('%d/%m/%Y')}</strong>
   au <strong>{date_fin.strftime('%d/%m/%Y')}</strong>)
   ne contient aucun <strong>{jour_nom}</strong>{parite_msg}.</p>
<p>La prochaine occurrence valide après le {date_debut.strftime('%d/%m/%Y')}
   est le <strong>{first_valid.strftime('%d/%m/%Y')}</strong>.<br>
   Merci de re-soumettre le formulaire avec une période incluant au moins un {jour_nom}{parite_msg}.</p>
<hr style="margin-top:32px;border:none;border-top:1px solid #eee">
<p style="font-size:0.85em;color:#888">
  Cours avec Chloé Ludmann — 6 rue Desaix, 35000 Rennes<br>
  <a href="https://chloeludmann.fr">chloeludmann.fr</a>
</p>
</body></html>"""
        try:
            send_email(email, "Votre demande de cours — période à corriger", html_no_occ)
            log.info(f"Email aucune occurrence envoyé à {email}")
        except Exception as e:
            log.error(f"Erreur email aucune occurrence : {e}")
        return jsonify({
            "status":  "warning",
            "reason":  f"Aucun {jour_nom}{parite_msg} dans la période {date_debut} → {date_fin}",
            "premier_jour_valide": first_valid.strftime("%d/%m/%Y"),
        }), 200

    # ── Vérification + réservation ──────────────────────────────────────────
    reserves      = []   # (date_locale, invitee_uri)
    en_attente    = []   # date_locale — hors fenêtre 60j, sauvegardé en DB
    indisponibles = []   # date_locale — vraiment indisponible dans la fenêtre
    erreurs       = []   # (date_locale, raison)

    for date_locale, dt_utc in occurrences:
        statut, detail = check_and_book(event_type_uri, location, dt_utc, nom, email)
        if statut == "booked":
            reserves.append((date_locale, detail.get("cancel_url", ""), detail.get("reschedule_url", "")))
        elif statut == "pending":
            en_attente.append(date_locale)
            save_pending(nom, prenom_affiche, email, event_type_uri, location,
                         dt_utc, heure_str, type_cours, jour_nom, frequence)
        elif statut == "unavailable":
            indisponibles.append(date_locale)
        else:
            erreurs.append((date_locale, detail))

    log.info(
        f"Résultat : {len(reserves)} réservés / {len(en_attente)} en attente / "
        f"{len(indisponibles)} indisponibles / {len(erreurs)} erreurs"
    )

    # ── Email récap au client ───────────────────────────────────────────────
    reserves_d      = [{"date": d.strftime("%d/%m/%Y"), "jour_nom": jour_nom, "heure_str": heure_str, "cu": cu, "ru": ru} for d, cu, ru in reserves]
    en_attente_d    = [{"date": d.strftime("%d/%m/%Y"), "jour_nom": jour_nom, "heure_str": heure_str} for d in en_attente]
    indisponibles_d = [{"date": d.strftime("%d/%m/%Y"), "heure_str": heure_str} for d in indisponibles]
    erreurs_d       = [{"date": d.strftime("%d/%m/%Y"), "r": r} for d, r in erreurs]

    html_client = build_email_client(
        prenom_affiche, type_cours, jour_nom, heure_str, freq_label,
        date_debut.strftime("%d/%m/%Y"), date_fin.strftime("%d/%m/%Y"),
        reserves_d, en_attente_d, indisponibles_d,
    )
    try:
        send_email(email, "Vos cours de chant — confirmation des réservations", html_client)
        log.info(f"Email récap envoyé à {email}")
    except Exception as e:
        log.error(f"Erreur email client : {e}")

    # ── Notification Chloé ──────────────────────────────────────────────────
    html_chloe = build_email_chloe(
        nom, email, type_cours, jour_nom, heure_str, freq_label,
        date_debut.strftime("%d/%m/%Y"), date_fin.strftime("%d/%m/%Y"),
        reserves_d, en_attente_d, indisponibles_d, erreurs_d,
    )
    try:
        send_email(
            CHLOE_EMAIL,
            f"[Récurrence] {nom} — {jour_nom} {heure_str} "
            f"({len(reserves)} réservés / {len(en_attente)} en attente / {len(occurrences)} total)",
            html_chloe,
        )
        log.info("Notification envoyée à Chloé")
    except Exception as e:
        log.error(f"Erreur notification Chloé : {e}")

    return jsonify({
        "status":        "ok",
        "reserves":      len(reserves),
        "en_attente":    len(en_attente),
        "indisponibles": len(indisponibles),
        "erreurs":       len(erreurs),
        "occurrences":   len(occurrences),
    }), 200


@app.route("/recurrence-webhook/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5007, debug=False)
