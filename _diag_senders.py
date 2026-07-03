"""Liste tous les expéditeurs dans la fenêtre IMAP."""
import os, imaplib, email
from email.header import decode_header
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

def decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            result.append(part)
    return " ".join(result)

since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")

with imaplib.IMAP4_SSL("ssl0.ovh.net", 993) as imap:
    imap.login(os.environ["IMAP_EMAIL"], os.environ["IMAP_PASSWORD"])
    imap.select("INBOX")
    _, data = imap.search(None, f"SINCE {since_date}")
    ids = data[0].split()
    print(f"{len(ids)} email(s) depuis {since_date}\n")
    for uid in ids:
        _, msg_data = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT)])")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        print(f"  De      : {decode_str(msg.get('From', ''))}")
        print(f"  Date    : {msg.get('Date', '')}")
        print(f"  Sujet   : {decode_str(msg.get('Subject', ''))}")
        print()
