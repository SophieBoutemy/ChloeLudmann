import imaplib, email as emaillib, os
from email.header import decode_header
from email.utils import getaddresses
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DAYS_BACK = 90

def decode_subject(raw):
    parts = decode_header(raw or "")
    result = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="ignore")
        else:
            result += part
    return result.strip()

def check_account(label, email, password, server, folder):
    print(f"\n=== {label} ({server}) ===")
    try:
        imap = imaplib.IMAP4_SSL(server, 993)
        imap.login(email, password)
    except Exception as e:
        print(f"  ERREUR : {e}")
        return

    status, _ = imap.select(f'"{folder}"', readonly=True)
    if status != "OK":
        print(f"  ERREUR ouverture '{folder}'")
        imap.logout()
        return

    since = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%d-%b-%Y")
    _, data = imap.search(None, f"SINCE {since}")
    ids = data[0].split() if data[0] else []
    print(f"  {len(ids)} emails dans '{folder}' sur {DAYS_BACK}j")

    # Show top 10 by recipient count
    rows = []
    for msg_id in ids:
        _, raw = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (TO CC BCC SUBJECT DATE)])")
        msg = emaillib.message_from_bytes(raw[0][1])
        to  = len(getaddresses([msg.get("To", "")]))
        cc  = len(getaddresses([msg.get("Cc", "")]))
        bcc = len(getaddresses([msg.get("Bcc", "")]))
        subj = decode_subject(msg.get("Subject", ""))[:60]
        rows.append((to + cc + bcc, to, cc, bcc, subj))

    rows.sort(reverse=True)
    print(f"  Top 10 par nombre de destinataires (To+Cc+Bcc) :")
    for total, to, cc, bcc, subj in rows[:10]:
        print(f"    {total:3d} dest. (To:{to} Cc:{cc} Bcc:{bcc})  {subj}")

    imap.close(); imap.logout()


check_account(
    "Chloé", os.environ["IMAP_EMAIL"], os.environ["IMAP_PASSWORD"],
    "ssl0.ovh.net", 'INBOX.Envoy&AOk-s'
)
check_account(
    "Whisper", os.environ["IMAP_EMAIL_WHISPER"], os.environ["IMAP_PASSWORD_WHISPER"],
    "mail.infomaniak.com", "Sent"
)
