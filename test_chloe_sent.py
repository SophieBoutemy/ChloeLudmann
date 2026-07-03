import imaplib, os
from dotenv import load_dotenv

load_dotenv()

imap = imaplib.IMAP4_SSL("ssl0.ovh.net", 993)
imap.login(os.environ["IMAP_EMAIL"], os.environ["IMAP_PASSWORD"])
_, folders = imap.list()
for f in folders:
    print(f.decode())
imap.logout()
