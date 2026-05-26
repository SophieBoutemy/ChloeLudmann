#!/usr/bin/env python3
"""
daily_summary.py
Résumé quotidien des événements Notion (24h) → mail via SMTP OVH.

Usage : python daily_summary.py
Cron  : 0 18 * * * cd /home/ubuntu/automations && venv/bin/python daily_summary.py >> logs/daily_summary.log 2>&1
"""

import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY    = os.environ["NOTION_API_KEY"]
NOTION_EVENTS_DB  = "35eafa74cfc980d092d0e80644bd6be7"

SMTP_HOST     = "ssl0.ovh.net"
SMTP_PORT     = 587
SMTP_USER     = os.environ["IMAP_EMAIL"]
SMTP_PASSWORD = os.environ["IMAP_PASSWORD"]

MAIL_FROM = "contact@chloeludmann.fr"
MAIL_TO   = ["contact@chloeludmann.fr", "bour.chloe0@gmail.com"]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
NOTION_BASE  = "https://api.notion.com/v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


# ── Notion ──────────────────────────────────────────────────────────────────────

def _notion_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    })
    return s


def _query_all(session: requests.Session, filter_: dict) -> list[dict]:
    pages, cursor = [], None
    while True:
        body: dict = {"filter": filter_}
        if cursor:
            body["start_cursor"] = cursor
        r = session.post(f"{NOTION_BASE}/databases/{NOTION_EVENTS_DB}/query", json=body)
        r.raise_for_status()
        res = r.json()
        pages.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return pages


def get_recent_events(hours: int = 24) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return _query_all(_notion_session(), {
        "or": [
            {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since}},
            {"timestamp": "created_time",     "created_time":     {"on_or_after": since}},
        ]
    })


def get_overdue_contracts(days: int = 8) -> list[dict]:
    """Contrats 'En attente' dont la date d'envoi est antérieure à {days} jours."""
    before = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    return _query_all(_notion_session(), {
        "and": [
            {"property": "Statut contrat envoyé", "select":   {"equals":   "En attente"}},
            {"property": "Date contrat envoyé",   "date":     {"before":   before}},
        ]
    })


# ── Formatting ──────────────────────────────────────────────────────────────────

def _prop_text(props: dict, name: str, type_: str) -> str:
    parts = props.get(name, {}).get(type_, [])
    return parts[0]["plain_text"] if parts else ""


def _prop_select(props: dict, name: str) -> str:
    sel = props.get(name, {}).get("select")
    return sel["name"] if sel else ""


def _prop_date(props: dict, name: str) -> str:
    d = props.get(name, {}).get("date")
    return d["start"] if d else ""


def page_to_line(page: dict) -> str:
    props    = page.get("properties", {})
    titre    = _prop_text(props,   "Titre",            "title")
    statut   = _prop_select(props, "Statut contrat envoyé")
    info_cal = _prop_text(props,   "Infos Calendly",   "rich_text")
    resume   = _prop_text(props,   "Résumé du mail",   "rich_text")
    date_m   = _prop_date(props,   "Date du mail")

    parts = [f"• {titre or '(sans titre)'}"]
    if info_cal:
        parts.append(f"  Calendly : {info_cal}")
    if statut:
        parts.append(f"  Contrat  : {statut}")
    if resume:
        parts.append(f"  Message  : {resume}")
    if date_m:
        parts.append(f"  Date     : {date_m}")
    return "\n".join(parts)


def overdue_to_line(page: dict) -> str:
    props       = page.get("properties", {})
    titre       = _prop_text(props, "Titre",              "title")
    date_envoi  = _prop_date(props, "Date contrat envoyé")
    jours       = ""
    if date_envoi:
        delta = (datetime.now().date() - datetime.fromisoformat(date_envoi).date()).days
        jours = f" ({delta}j)"
    return f"• {titre or '(sans titre)'}{jours}"


# ── Claude ───────────────────────────────────────────────────────────────────────

SUMMARY_PROMPT = """\
Tu es l'assistant de Chloé Ludmann, professeure de chant.
Voici les événements Notion modifiés ou créés dans les dernières 24h :

{events}

Génère un résumé quotidien clair et structuré en français, organisé en sections :
- Nouvelles demandes / premiers contacts
- Confirmations Calendly
- Annulations
- Contrats en attente de signature
- Contrats signés

Règles : omets les sections vides, 2-3 lignes max par section, ton professionnel et concis.\
"""


def build_summary(pages: list[dict], overdue: list[dict]) -> str:
    events_text = "\n\n".join(page_to_line(p) for p in pages)
    client      = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response    = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(events=events_text)}],
    )
    summary = response.content[0].text.strip()

    if overdue:
        lines        = "\n".join(overdue_to_line(p) for p in overdue)
        overdue_bloc = f"\n\n⚠️ Contrats en attente depuis plus de 8 jours\n{lines}"
        summary     += overdue_bloc

    return summary


# ── SMTP ─────────────────────────────────────────────────────────────────────────

def send_mail(subject: str, body: str) -> None:
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MAIL_FROM
    msg["To"]      = ", ".join(MAIL_TO)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())


# ── Main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Récupération des événements des dernières 24h...")
    pages = get_recent_events()
    log.info(f"{len(pages)} événement(s) trouvé(s)")

    if not pages:
        log.info("Rien à signaler — mail non envoyé")
        return

    log.info("Récupération des contrats en attente depuis +8j...")
    overdue = get_overdue_contracts()
    log.info(f"{len(overdue)} contrat(s) en retard")

    summary = build_summary(pages, overdue)
    log.info("Résumé généré")

    now        = datetime.now()
    jours_fr   = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr    = ["janvier", "février", "mars", "avril", "mai", "juin",
                  "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    date_label = f"{jours_fr[now.weekday()]} {now.day} {mois_fr[now.month - 1]} {now.year}"
    subject    = f"📋 Résumé du jour – {date_label}"

    send_mail(subject, summary)
    log.info(f"Mail envoyé à : {', '.join(MAIL_TO)}")

    print("\n" + summary)


if __name__ == "__main__":
    main()
