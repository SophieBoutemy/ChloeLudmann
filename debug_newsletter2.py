import imaplib, email as emaillib, os
from email.header import decode_header
from email.utils import getaddresses
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

imap = imaplib.IMAP4_SSL("mail.infomaniak.com", 993)
imap.login(os.environ["IMAP_EMAIL_WHISPER"], os.environ["IMAP_PASSWORD_WHISPER"])
imap.select("Sent", readonly=True)

since = (datetime.now() - timedelta(days=90)).strftime("%d-%b-%Y")
_, data = imap.search(None, f"SINCE {since}")
ids = data[0].split()

print(f"{len(ids)} emails trouvés\n")
for mid in ids:
    _, raw = imap.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (TO CC BCC SUBJECT DATE)])")
    msg = emaillib.message_from_bytes(raw[0][1])
    to  = len(getaddresses([msg.get("To", "")]))
    cc  = len(getaddresses([msg.get("Cc", "")]))
    bcc = len(getaddresses([msg.get("Bcc", "")]))
    total = to + cc + bcc
    if total > 5:
        subj_raw = msg.get("Subject", "")
        parts = decode_header(subj_raw)
        subj = ""
        for part, charset in parts:
            if isinstance(part, bytes):
                subj += part.decode(charset or "utf-8", errors="ignore")
            else:
                subj += str(part)
        print(f"  To:{to} Cc:{cc} Bcc:{bcc} = {total}  '{subj[:60]}'")

imap.logout()
