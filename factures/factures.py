#!/usr/bin/env python3
# Detecte les factures dans les boites mail IMAP, uploade sur Drive, cree les entrees Notion.
import os, imaplib, email, email.header, io, base64
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv
import anthropic
import requests

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

NOTION_API_KEY       = os.environ['NOTION_API_KEY']
NOTION_DB_ID         = '327afa74cfc980328301eec9bb7996e5'
ANTHROPIC_KEY        = os.environ['ANTHROPIC_API_KEY']
CLAUDE_MODEL         = 'claude-haiku-4-5-20251001'
DRIVE_FOLDER_ID      = os.environ.get('DRIVE_FOLDER_ID', '')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'token.json')

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
]

# ── Claude ────────────────────────────────────────────────────────────────────

INVOICE_KEYWORDS = {'invoice', 'facture', 'inv', 'receipt', 'recu', 'recus', 'billing', 'statement', 'payment confirmation', 'order confirmation'}

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

# ── Google Drive ──────────────────────────────────────────────────────────────

def _drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(
        TOKEN_FILE,
        scopes=['https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/drive.file'],
    )
    return build('drive', 'v3', credentials=creds)

def _get_or_create_year_folder(svc, year: str) -> str:
    q = (f"name='{year}' and '{DRIVE_FOLDER_ID}' in parents "
         f"and mimeType='application/vnd.google-apps.folder' and trashed=false")
    res = svc.files().list(q=q, fields='files(id)').execute()
    files = res.get('files', [])
    if files:
        return files[0]['id']
    meta = {
        'name': year,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [DRIVE_FOLDER_ID],
    }
    return svc.files().create(body=meta, fields='id').execute()['id']

def upload_to_drive(filename: str, pdf_bytes: bytes, year: str) -> str:
    if not DRIVE_FOLDER_ID or not os.path.exists(TOKEN_FILE):
        return ''
    try:
        from googleapiclient.http import MediaIoBaseUpload
        svc = _drive_service()
        folder_id = _get_or_create_year_folder(svc, year)
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
        meta = {'name': filename, 'parents': [folder_id]}
        f = svc.files().create(body=meta, media_body=media, fields='id,webViewLink').execute()
        return f.get('webViewLink', '')
    except Exception as e:
        print(f"    Drive erreur : {e}")
        return ''

# ── Notion ────────────────────────────────────────────────────────────────────

def create_notion_entry(nom: str, date_reception: str, expediteur: str, drive_link: str = ''):
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json',
    }
    r = requests.post(
        f'https://api.notion.com/v1/databases/{NOTION_DB_ID}/query',
        headers=headers,
        json={'filter': {'property': 'Nom de la facture', 'title': {'equals': nom}}},
    )
    existing = r.json().get('results', []) if r.ok else []
    if existing:
        page_id = existing[0]['id']
        if drive_link:
            r = requests.patch(
                f'https://api.notion.com/v1/pages/{page_id}',
                headers=headers,
                json={'properties': {'Lien Drive': {'url': drive_link}}},
            )
            if not r.ok:
                print(f"    Notion erreur MAJ {r.status_code}: {r.text[:300]}")
            else:
                print(f"    Notion MAJ lien Drive OK")
        else:
            print(f"    Notion doublon ignore")
        return
    props = {
        'Nom de la facture':     {'title': [{'text': {'content': nom}}]},
        'Date de réception':     {'date': {'start': date_reception}},
        'Expéditeur':            {'rich_text': [{'text': {'content': expediteur}}]},
        'Envoyé à la comptable': {'checkbox': False},
    }
    if drive_link:
        props['Lien Drive'] = {'url': drive_link}
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
    since_date = (datetime.today() - timedelta(days=10)).strftime('%d-%b-%Y')
    _, data = conn.search(None, f'(UNSEEN SINCE {since_date})')
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
            year         = str(received_dt.year)
        except Exception:
            received_iso = datetime.today().date().isoformat()
            year         = str(datetime.today().year)

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
                    pdfs.append((fname, payload))

        if not pdfs:
            conn.store(uid, '+FLAGS', '\\Seen')
            continue

        for filename, pdf_bytes in pdfs:
            print(f"  PDF : {filename} | {subject[:50]}")
            if is_invoice(filename, subject):
                print(f"    -> Facture detectee")
                drive_link = upload_to_drive(filename, pdf_bytes, year)
                if drive_link:
                    print(f"    Drive OK : {drive_link[:60]}")
                create_notion_entry(filename, received_iso, sender, drive_link)
            else:
                print(f"    -> Pas une facture, ignore")

        conn.store(uid, '+FLAGS', '\\Seen')

    conn.logout()


# ── Gmail OAuth ───────────────────────────────────────────────────────────────

def get_gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(
        TOKEN_FILE,
        scopes=['https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/drive.file'],
    )
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def _gmail_get_pdf_parts(payload: dict) -> list:
    parts = []
    att_id = payload.get('body', {}).get('attachmentId')
    if att_id and payload.get('filename'):
        fname = payload['filename']
        ct = payload.get('mimeType', '')
        if ct == 'application/pdf' or fname.lower().endswith('.pdf'):
            parts.append((fname, att_id))
    for p in payload.get('parts', []):
        parts.extend(_gmail_get_pdf_parts(p))
    return parts

def process_gmail_oauth(days: int = 10):
    print(f"\n[Gmail OAuth] Connexion via token.json...")
    try:
        svc = get_gmail_service()
        since = (datetime.today() - timedelta(days=days)).strftime('%Y/%m/%d')
        result = svc.users().messages().list(
            userId='me',
            q=f'after:{since} in:inbox has:attachment',
            maxResults=500,
        ).execute()
        msg_ids = [m['id'] for m in result.get('messages', [])]
        print(f"  {len(msg_ids)} email(s) avec pieces jointes")

        for msg_id in msg_ids:
            full = svc.users().messages().get(userId='me', id=msg_id, format='full').execute()
            hdrs = {h['name']: h['value'] for h in full['payload']['headers']}
            subject  = hdrs.get('Subject', '')
            sender   = hdrs.get('From', '')
            date_str = hdrs.get('Date', '')
            try:
                received_dt  = parsedate_to_datetime(date_str)
                received_iso = received_dt.date().isoformat()
                year         = str(received_dt.year)
            except Exception:
                received_iso = datetime.today().date().isoformat()
                year         = str(datetime.today().year)

            pdf_parts = _gmail_get_pdf_parts(full['payload'])
            for filename, att_id in pdf_parts:
                print(f"  PDF : {filename} | {subject[:50]}")
                if is_invoice(filename, subject):
                    print(f"    -> Facture detectee")
                    att = svc.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=att_id,
                    ).execute()
                    pdf_bytes = base64.urlsafe_b64decode(att['data'])
                    drive_link = upload_to_drive(filename, pdf_bytes, year)
                    if drive_link:
                        print(f"    Drive OK : {drive_link[:60]}")
                    create_notion_entry(filename, received_iso, sender, drive_link)
                else:
                    print(f"    -> Pas une facture, ignore")
    except Exception as e:
        print(f"  Erreur Gmail OAuth : {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    reset_ovh_factures()
    for mb in MAILBOXES:
        process_mailbox(mb)
    process_gmail_oauth()
    print("\nTermine.")

if __name__ == '__main__':
    main()
