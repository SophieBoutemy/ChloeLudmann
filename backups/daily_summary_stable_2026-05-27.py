#!/usr/bin/env python3
"""
daily_summary.py
Résumé quotidien des événements Notion (24h) → mail HTML via Gmail.

Usage : python daily_summary.py
Cron  : 0 18 * * * cd /home/ubuntu/automations && venv/bin/python daily_summary.py >> logs/daily_summary.log 2>&1
"""

import logging
import os
import re
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

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = "boutemy.automatisation@gmail.com"
SMTP_PASSWORD = os.environ["GMAIL_AUTOMATION_PASSWORD"]

MAIL_FROM = "boutemy.automatisation@gmail.com"
MAIL_TO   = ["contact@chloeludmann.fr", "bour.chloe0@gmail.com"]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
NOTION_BASE  = "https://api.notion.com/v1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
    before = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    return _query_all(_notion_session(), {
        "and": [
            {"property": "Statut contrat envoyé", "select": {"equals": "En attente"}},
            {"property": "Date contrat envoyé",   "date":   {"before": before}},
        ]
    })


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _prop_text(props: dict, name: str, type_: str) -> str:
    parts = props.get(name, {}).get(type_, [])
    return parts[0]["plain_text"] if parts else ""


def _prop_select(props: dict, name: str) -> str:
    sel = props.get(name, {}).get("select")
    return sel["name"] if sel else ""


def _prop_date(props: dict, name: str) -> str:
    d = props.get(name, {}).get("date")
    return d["start"] if d else ""


def _titre_eleve(props: dict) -> str:
    """Identifiant d'un élève : champ Email (titre DB) ou Titre en fallback."""
    return (
        _prop_text(props, "Email", "title")
        or _prop_text(props, "Titre", "title")
        or _prop_text(props, "Titre", "rich_text")
    )


def _notion_url(page_id: str) -> str:
    return "https://notion.so/" + page_id.replace("-", "")


# ── Formatting ───────────────────────────────────────────────────────────────────

def page_to_line(page: dict) -> str:
    """Texte plat envoyé à Claude comme input."""
    props    = page.get("properties", {})
    titre    = _titre_eleve(props)
    statut   = _prop_select(props, "Statut contrat envoyé")
    info_cal = _prop_text(props, "Infos Calendly", "rich_text")
    resume   = _prop_text(props, "Résumé du mail", "rich_text")
    date_m   = _prop_date(props, "Date du mail")

    parts = [f"• {titre or '(sans identifiant)'}"]
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
    props      = page.get("properties", {})
    titre      = _titre_eleve(props)
    date_envoi = _prop_date(props, "Date contrat envoyé")
    url        = _notion_url(page["id"])
    jours = ""
    if date_envoi:
        delta = (datetime.now().date() - datetime.fromisoformat(date_envoi).date()).days
        jours = f' <span style="color:#AF4403;font-size:12px">({delta}j)</span>'
    label = titre or "(sans identifiant)"
    link  = f'<a href="{url}" style="color:#697A4D;text-decoration:none;font-weight:600">{label}</a>'
    return f"{link}{jours}"


def _build_email_url_map(pages: list[dict], overdue: list[dict]) -> dict[str, str]:
    """Construit un mapping email → URL Notion pour les élèves identifiés par email."""
    result = {}
    for page in pages + overdue:
        titre = _titre_eleve(page.get("properties", {})).strip()
        if titre and "@" in titre:
            result[titre.lower()] = _notion_url(page["id"])
    return result


def _linkify_emails(html: str, email_url_map: dict[str, str]) -> str:
    for email, url in email_url_map.items():
        html = re.sub(
            re.escape(email),
            f'<a href="{url}" style="color:#697A4D;text-decoration:none">{email}</a>',
            html,
            flags=re.IGNORECASE,
        )
    return html


def _strip_code_fence(text: str) -> str:
    text = re.sub(r"^```html?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text.strip())
    return text.strip()


# ── Claude ───────────────────────────────────────────────────────────────────────

SUMMARY_PROMPT = """\
Tu es l'assistant de Chloé Ludmann, professeure de chant.
Voici les événements Notion modifiés ou créés dans les dernières 24h :

{events}

Génère un résumé quotidien en HTML, en français.
Sections possibles (omets les vides) :
- Nouvelles demandes / premiers contacts
- Confirmations Calendly
- Annulations
- Contrats en attente de signature
- Contrats signés

Règles STRICTES :
- Commence DIRECTEMENT par le HTML, sans ``` ni préambule
- Chaque section est une carte : <div style="background:#ffffff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.07);padding:16px 20px;margin-bottom:16px">
- À l'intérieur de la carte, le titre : <p style="color:#354626;font-size:16px;font-weight:600;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #A1B482">Titre</p>
- Chaque entrée dans la carte : <p style="margin:0 0 12px 0"><strong style="color:#262525;font-size:14px">Nom ou email</strong> <span style="color:#6E6C68;font-size:12px">— description concise</span></p>
- Fermer chaque carte avec </div>
- 2-3 entrées max par section, ton professionnel et sobre
- Aucun Markdown, aucun ##, aucun bloc de code\
"""


def build_summary(pages: list[dict], overdue: list[dict]) -> str:
    events_text = "\n\n".join(page_to_line(p) for p in pages)
    client      = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response    = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(events=events_text)}],
    )
    content_html = _strip_code_fence(response.content[0].text)

    email_url_map = _build_email_url_map(pages, overdue)
    content_html  = _linkify_emails(content_html, email_url_map)

    overdue_html = ""
    if overdue:
        items = "\n".join(
            f'  <li style="margin:6px 0">{overdue_to_line(p)}</li>' for p in overdue
        )
        overdue_html = (
            '<div style="margin-top:32px;background:#F0F0F0;border-left:4px solid #C66A00;'
            'padding:14px 18px;border-radius:0 4px 4px 0">'
            '<p style="color:#AF4403;font-size:14px;font-weight:600;margin:0 0 10px 0">'
            '&#x26A0;&#xFE0F; Contrats en attente depuis plus de 8 jours</p>'
            f'<ul style="margin:0;padding-left:18px;color:#AF4403;font-size:14px">\n{items}\n</ul>'
            '</div>'
        )

    header_html = (
        '<div style="background:#354626;border-radius:8px;padding:24px 28px;margin-bottom:24px">'
        '<p style="color:#ffffff;font-size:16px;font-weight:600;margin:0 0 6px 0">Bonjour Chloé \U0001f44b</p>'
        '<p style="color:#ffffff;font-size:14px;margin:0;opacity:0.85">'
        "Voici ce que ton agent IA a relevé sur tes boîtes mail aujourd’hui.</p>"
        '</div>'
    )

    return (
        '<html><body style="background-color:#F9F6F3;margin:0;padding:32px 16px;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="max-width:620px;margin:0 auto">'
        + header_html
        + content_html
        + ("\n" + overdue_html if overdue_html else "")
        + '</div></body></html>'
    )


# ── SMTP ─────────────────────────────────────────────────────────────────────────

def send_mail(subject: str, body: str) -> None:
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MAIL_FROM
    msg["To"]      = ", ".join(MAIL_TO)
    msg.attach(MIMEText(body, "html", "utf-8"))

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
    log.info("HTML body length: %d chars", len(summary))


if __name__ == "__main__":
    main()
