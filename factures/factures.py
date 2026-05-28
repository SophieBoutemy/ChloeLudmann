#!/usr/bin/env python3
"""
Detecte les factures dans les boites mail IMAP et cree les entrees dans Notion.
Usage : python factures.py
"""
import os, imaplib, email, email.header
from datetime import datetime
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv
import anthropic
import requests

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

NOTION_API_KEY = os.environ['NOTION_API_KEY']
NOTION_DB_ID   = '327afa74cfc980328301eec9bb7996e5'
ANTHROPIC_KEY  = os.environ['ANTHROPIC_API_KEY']
CLAUDE_MODEL   = 'claude-haiku-4-5-20251001'

MAILBOXES = [
    {
        'label':    'OVH Chloe',
        'email':    os.environ['IMAP_EMAIL'],
        'password': os.environ['IMAP_PASSWORD'],
        'host':     'ssl0.ovh.net',
        'port':     993,
    },
    {
        'label':    'Infomaniak Whisper',
        'email':    os.environ['IMAP_EMAIL_WHISPER'],
        'password': os.environ['IMAP_PASSWORD_WHISPER'],
        'host':     'mail.infomaniak.com',
        'port':     993,
    },
    {
        'label':    'Gmail',
        'email':    os.environ.get('GMAIL_IMAP_EMAIL', 'bour.chloe0@gmail.com'),
        'password': os.environ['GMAIL_AUTOMATION_PASSWORD'],
        'host':     'imap.gmail.com',
        'port':     993,
    },
]

# ── Claude ────────────────────────────────────────────────────────────────────

INVOICE_KEYWORDS = {'invoice', 'facture', 'inv', 'receipt', 'recu', 'recus'}

def _contains_keyword(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in INVOICE_KEYWORDS)

def is_invoice(filename: str, subject: str) -> bool:
    if _contains_keyword(filename) or _contains_keyword(subject):
        return True
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        f"Nom du fichier : {filename}\n"
        f"Objet du mail : {subject}\n\n"
        "Est-ce une facture ou invoice ? Reponds uniquement par 'oui' ou 'non'."
    )
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        system=[{
            "type": "text",
            "text": "Tu identifies si un document est une facture. Reponds uniquement 'oui' ou 'non'.",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return 'oui' in response.content[0].text.strip().lower()

# ── Notion ────────────────────────────────────────────────────────────────────

def create_notion_entry(nom: str, date_reception: str, expediteur: str):
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json',
    }
    props = {
        'Nom de la facture':     {'title': [{'text': {'content': nom}}]},
        'Date de réception':     {'date': {'start': date_reception}},
        'Expéditeur':            {'rich_text': [{'text': {'content': expediteur}}]},
        'Envoyé à la comptable': {'checkbox': False},
    }
    r = requests.post('https://api.notion.com/v1/pages', headers=headers, json={
        'parent': {'database_id': NOTION_DB_ID},
        'properties': props,
    })
    if not r.ok:
        print(f"    Notion erreur {r.status_code}: {r.text[:300]}")
    else:
        print(f"    Notion OK")

# ── IMAP ──────────────────────────────────────────────────────────────────────

def decode_str(value: str) -> str:
    parts = email.header.decode_header(value or '')
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or 'utf-8', errors='replace'))
            except (LookupError, UnicodeDecodeError):
                out.append(part.decode('utf-8', errors='replace'))
        else:
            out.append(part)
    return ''.join(out)

def reset_ovh_factures():
    """Remet en non-lu les emails de factures deja traites sur OVH contact@chloeludmann.fr."""
    mb = MAILBOXES[0]
    print(f"[reset] Connexion a {mb['host']} ({mb['email']})...")
    conn = imaplib.IMAP4_SSL(mb['host'], mb['port'])
    conn.login(mb['email'], mb['password'])
    conn.select('INBOX')

    # Sujets ASCII identifiant les emails de factures traites
    invoice_subjects = [
        'Your receipt from Calendly LLC',
        '5124603268',
    ]
    total = 0
    for subj in invoice_subjects:
        _, data = conn.search(None, f'SUBJECT "{subj}"')
        uids = [u for u in data[0].split() if u]
        for uid in uids:
            conn.store(uid, '-FLAGS', '\\Seen')
        print(f"  {len(uids)} emails remis en non-lu : {subj}")
        total += len(uids)

    conn.logout()
    print(f"[reset] {total} emails non lus au total\n")

def process_mailbox(mb: dict):
    print(f"\n[{mb['label']}] Connexion a {mb['host']}...")
    try:
        conn = imaplib.IMAP4_SSL(mb['host'], mb['port'])
        conn.login(mb['email'], mb['password'])
    except Exception as e:
        print(f"  Erreur connexion : {e}")
        return

    conn.select('INBOX')
    _, data = conn.search(None, 'UNSEEN')
    uids = [u for u in data[0].split() if u]
    print(f"  {len(uids)} email(s) non lu(s)")

    for uid in uids:
        _, msg_data = conn.fetch(uid, '(RFC822)')
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject  = decode_str(msg.get('Subject', ''))
        sender   = decode_str(msg.get('From', ''))
        date_str = msg.get('Date', '')

        try:
            received_dt  = parsedate_to_datetime(date_str)
            received_iso = received_dt.date().isoformat()
        except Exception:
            received_iso = datetime.today().date().isoformat()

        pdfs = []
        for part in msg.walk():
            fname = part.get_filename()
            if not fname:
                continue
            fname = decode_str(fname)
            ct = part.get_content_type()
            if ct == 'application/pdf' or fname.lower().endswith('.pdf'):
                payload = part.get_payload(decode=True)
                if payload:
                    pdfs.append(fname)

        if not pdfs:
            conn.store(uid, '+FLAGS', '\\Seen')
            continue

        for filename in pdfs:
            print(f"  PDF : {filename} | {subject[:50]}")
            if is_invoice(filename, subject):
                print(f"    -> Facture detectee")
                create_notion_entry(filename, received_iso, sender)
            else:
                print(f"    -> Pas une facture, ignore")

        conn.store(uid, '+FLAGS', '\\Seen')

    conn.logout()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    reset_ovh_factures()
    for mb in MAILBOXES:
        process_mailbox(mb)
    print("\nTermine.")

if __name__ == '__main__':
    main()