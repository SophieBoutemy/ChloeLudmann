import imaplib, os
from dotenv import load_dotenv

load_dotenv()

email = os.environ["IMAP_EMAIL_WHISPER"]
password = os.environ["IMAP_PASSWORD_WHISPER"]

print(f"Connexion IMAP {email}...")

try:
    imap = imaplib.IMAP4_SSL("mail.infomaniak.com", 993)
    imap.login(email, password)
    print("  Connexion OK")
    status, folders = imap.list()
    print("  Dossiers disponibles :")
    for f in folders:
        print(f"    {f.decode()}")
    imap.logout()
except imaplib.IMAP4.error as e:
    print(f"  ERREUR : {e}")
except Exception as e:
    print(f"  ERREUR inattendue : {e}")
