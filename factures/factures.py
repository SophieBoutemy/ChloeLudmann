#!/usr/bin/env python3
# Detecte les factures dans les boites mail IMAP, uploade sur Drive, cree les entrees Notion.
import os, imaplib, email, email.header, io, base64, hashlib
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

IMAGE_MEDIA_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
_MAX_IMAGE_BYTES = 5_000_000  # evite d'envoyer une image demesuree a l'API

def _sniff_image_media_type(data: bytes, filename: str = '') -> str:
    """Devine le vrai type MIME depuis les octets magiques -- ni l'extension du fichier ni le
    Content-Type declare par l'expediteur ne sont fiables (ex. capture d'ecran renommee .png
    alors que le contenu reel est un JPEG) ; Claude rejette l'appel si le media_type annonce ne
    correspond pas au contenu reel."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    ext = os.path.splitext(filename)[1].lower()
    return IMAGE_MEDIA_TYPES.get(ext, 'image/jpeg')

def is_invoice_image(filename: str, subject: str, image_bytes: bytes, media_type: str = '') -> bool:
    """Verification visuelle via Claude (vision) plutot que texte seul : contrairement aux PDF,
    les images de facture (photo, scan) ont presque toujours un nom de fichier generique
    (IMG_1234.jpg, Scan001.png) qui ne donne aucun indice — le contenu doit etre regarde."""
    if _contains_keyword(filename) or _contains_keyword(subject):
        return True
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        return False
    media_type = _sniff_image_media_type(image_bytes, filename)
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    b64 = base64.b64encode(image_bytes).decode('ascii')
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        system=[{
            "type": "text",
            "text": "Tu identifies si une image represente une facture, un recu ou un justificatif de paiement. Reponds uniquement 'oui' ou 'non'.",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": f"Nom du fichier : {filename}\nObjet du mail : {subject}\n\nEst-ce une facture, un reçu, ou un justificatif de paiement ?"},
            ],
        }],
    )
    return 'oui' in response.content[0].text.strip().lower()

# ── Google Drive ──────────────────────────────────────────────────────────────

def _drive_service():
    """OAuth utilisateur (token.json), pas un compte de service : teste et confirme non
    fonctionnel pour ecrire dans ce dossier (compte de service = 0 quota de stockage propre,
    hors Shared Drive / delegation domain-wide -- toutes deux indisponibles sur un compte
    @gmail.com personnel comme bour.chloe0@gmail.com). Voir CLAUDE.md pour le detail."""
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

def _notion_headers():
    return {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json',
    }

def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def find_notion_entry(nom: str) -> list:
    """Retourne TOUTES les entrees Notion partageant ce nom de fichier -- un fournisseur peut
    reutiliser un nom generique (facture.pdf) pour des factures differentes, donc le nom seul
    ne suffit pas a identifier un doublon (voir find_matching_entry)."""
    r = requests.post(
        f'https://api.notion.com/v1/databases/{NOTION_DB_ID}/query',
        headers=_notion_headers(),
        json={'filter': {'property': 'Nom de la facture', 'title': {'equals': nom}}},
    )
    return r.json().get('results', []) if r.ok else []

def find_matching_entry(nom: str, content_hash: str, received_iso: str):
    """Parmi les entrees partageant ce nom de fichier, retrouve celle qui correspond vraiment :
    priorite au hash de contenu (fiable a 100%) ; a defaut de hash enregistre (anciennes
    entrees), on se rabat sur la date de reception du mail."""
    candidates = find_notion_entry(nom)
    for c in candidates:
        existing_hash = ''.join(t['plain_text'] for t in c.get('properties', {}).get('Hash contenu', {}).get('rich_text', []))
        if existing_hash and existing_hash == content_hash:
            return c
    for c in candidates:
        props = c.get('properties', {})
        existing_hash = ''.join(t['plain_text'] for t in props.get('Hash contenu', {}).get('rich_text', []))
        existing_date = (props.get('Date de réception', {}).get('date') or {}).get('start', '')
        if not existing_hash and existing_date and existing_date == received_iso:
            return c
    return None

def notion_entry_has_drive_link(entry: dict) -> bool:
    return bool(entry.get('properties', {}).get('Lien Drive', {}).get('url'))

def create_notion_entry(nom: str, date_reception: str, expediteur: str, drive_link: str = '', content_hash: str = ''):
    """Cree une nouvelle entree Notion. L'appelant doit avoir verifie via find_matching_entry qu'elle n'existe pas deja."""
    props = {
        'Nom de la facture':     {'title': [{'text': {'content': nom}}]},
        'Date de réception':     {'date': {'start': date_reception}},
        'Expéditeur':            {'rich_text': [{'text': {'content': expediteur}}]},
        'Envoyé à la comptable': {'checkbox': False},
    }
    if drive_link:
        props['Lien Drive'] = {'url': drive_link}
    if content_hash:
        props['Hash contenu'] = {'rich_text': [{'text': {'content': content_hash}}]}
    r = requests.post('https://api.notion.com/v1/pages', headers=_notion_headers(), json={
        'parent': {'database_id': NOTION_DB_ID},
        'properties': props,
    })
    if not r.ok:
        print(f"    Notion erreur {r.status_code}: {r.text[:300]}")
    else:
        print(f"    Notion OK")

def update_notion_drive_link(page_id: str, drive_link: str):
    r = requests.patch(
        f'https://api.notion.com/v1/pages/{page_id}',
        headers=_notion_headers(),
        json={'properties': {'Lien Drive': {'url': drive_link}}},
    )
    if not r.ok:
        print(f"    Notion erreur MAJ {r.status_code}: {r.text[:300]}")
    else:
        print(f"    Notion MAJ lien Drive OK")

def handle_invoice_file(filename: str, subject: str, sender: str, received_iso: str, year: str,
                         file_bytes: bytes, is_image: bool = False) -> None:
    """Deduplique via nom de fichier + hash de contenu (ou date de reception a defaut) avant
    tout upload Drive ou creation Notion. Fonctionne pour un PDF ou une image (facture photo/scan)."""
    content_hash = _content_hash(file_bytes)
    existing = find_matching_entry(filename, content_hash, received_iso)
    if existing:
        if notion_entry_has_drive_link(existing):
            print(f"    -> Deja traite (Notion + Drive), ignore")
            return
        print(f"    -> Facture deja connue sans lien Drive, nouvelle tentative d'upload")
        drive_link = upload_to_drive(filename, file_bytes, year)
        if drive_link:
            print(f"    Drive OK : {drive_link[:60]}")
            update_notion_drive_link(existing['id'], drive_link)
        return

    if is_image:
        detected = is_invoice_image(filename, subject, file_bytes)
    else:
        detected = is_invoice(filename, subject)

    if not detected:
        print(f"    -> Pas une facture, ignore")
        return

    print(f"    -> Facture detectee")
    drive_link = upload_to_drive(filename, file_bytes, year)
    if drive_link:
        print(f"    Drive OK : {drive_link[:60]}")
    create_notion_entry(filename, received_iso, sender, drive_link, content_hash)

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

def process_mailbox(mb: dict):
    print(f"\n[{mb['label']}] Connexion a {mb['host']}...")
    try:
        conn = imaplib.IMAP4_SSL(mb['host'], mb['port'])
        conn.login(mb['email'], mb['password'])
    except Exception as e:
        print(f"  Erreur connexion : {e}")
        return

    conn.select('INBOX', readonly=True)
    since_date = (datetime.today() - timedelta(days=10)).strftime('%d-%b-%Y')
    _, data = conn.search(None, f'(SINCE {since_date})')
    uids = [u for u in data[0].split() if u]
    print(f"  {len(uids)} email(s) sur la periode (lus + non lus)")

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

        attachments = []
        for part in msg.walk():
            fname = part.get_filename()
            if not fname:
                continue
            fname = decode_str(fname)
            ct = part.get_content_type()
            ext = os.path.splitext(fname)[1].lower()
            is_pdf = ct == 'application/pdf' or ext == '.pdf'
            # Volontairement restreint au JPEG/PNG (voir IMAGE_MEDIA_TYPES) : le GIF n'est jamais
            # une facture en pratique (logos de signature, icones de notification) et n'est de
            # toute facon pas un des deux types geres par _sniff_image_media_type.
            is_img = ext in IMAGE_MEDIA_TYPES or ct in ('image/jpeg', 'image/png')
            if is_pdf or is_img:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((fname, payload, is_img))

        for filename, file_bytes, is_img in attachments:
            print(f"  {'IMG' if is_img else 'PDF'} : {filename} | {subject[:50]}")
            handle_invoice_file(filename, subject, sender, received_iso, year, file_bytes, is_image=is_img)

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

def _gmail_get_attachment_parts(payload: dict) -> list:
    """Retourne (nom, attachment_id, is_image) pour chaque piece jointe PDF ou image."""
    parts = []
    att_id = payload.get('body', {}).get('attachmentId')
    if att_id and payload.get('filename'):
        fname = payload['filename']
        ct = payload.get('mimeType', '')
        ext = os.path.splitext(fname)[1].lower()
        is_pdf = ct == 'application/pdf' or ext == '.pdf'
        # Restreint au JPEG/PNG -- voir commentaire equivalent dans process_mailbox()
        is_img = ext in IMAGE_MEDIA_TYPES or ct in ('image/jpeg', 'image/png')
        if is_pdf or is_img:
            parts.append((fname, att_id, is_img))
    for p in payload.get('parts', []):
        parts.extend(_gmail_get_attachment_parts(p))
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

            att_parts = _gmail_get_attachment_parts(full['payload'])
            for filename, att_id, is_img in att_parts:
                print(f"  {'IMG' if is_img else 'PDF'} : {filename} | {subject[:50]}")
                # Le hash de contenu impose de recuperer les octets tout de suite (avant de savoir
                # si c'est une facture), plutot que de differer l'appel comme avant.
                att = svc.users().messages().attachments().get(
                    userId='me', messageId=msg_id, id=att_id,
                ).execute()
                file_bytes = base64.urlsafe_b64decode(att['data'])
                handle_invoice_file(filename, subject, sender, received_iso, year, file_bytes, is_image=is_img)
    except Exception as e:
        print(f"  Erreur Gmail OAuth : {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    for mb in MAILBOXES:
        process_mailbox(mb)
    process_gmail_oauth()
    print("\nTermine.")

if __name__ == '__main__':
    main()
