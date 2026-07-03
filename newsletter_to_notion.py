import imaplib, email as emaillib, os, re
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from notion_client import Client as NotionClient

load_dotenv()

NOTION_EVENTS_DB  = os.environ["NOTION_EVENTS_DATABASE_ID"]
DAYS_BACK         = 90
MIN_RECIPIENTS    = 15

ACCOUNTS = [
    {
        "label":       "Chloé",
        "email":       os.environ["IMAP_EMAIL"],
        "password":    os.environ["IMAP_PASSWORD"],
        "server":      "ssl0.ovh.net",
        "sent_folder": 'INBOX.Envoy&AOk-s',
    },
    {
        "label":       "Whisper",
        "email":       os.environ["IMAP_EMAIL_WHISPER"],
        "password":    os.environ["IMAP_PASSWORD_WHISPER"],
        "server":      "mail.infomaniak.com",
        "sent_folder": "Sent",
    },
]


def decode_subject(raw: str) -> str:
    parts = decode_header(raw or "")
    result = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="ignore")
        else:
            result += part
    return result.strip()


def count_recipients(msg) -> int:
    headers = [h for h in [msg.get("To",""), msg.get("Cc",""), msg.get("Bcc","")] if h.strip()]
    return len(getaddresses(headers))


def parse_send_date(msg) -> str:
    today = date.today()
    try:
        d = parsedate_to_datetime(msg.get("Date", "")).date()
        return today.strftime("%Y-%m-%d") if d > today else d.strftime("%Y-%m-%d")
    except Exception:
        return today.strftime("%Y-%m-%d")


def newsletter_exists(notion: NotionClient, subject: str) -> bool:
    r = notion.databases.query(
        database_id=NOTION_EVENTS_DB,
        filter={"property": "Titre", "title": {"equals": subject[:100]}},
    )
    return bool(r.get("results"))


def create_newsletter_event(notion: NotionClient, subject: str, send_date: str) -> None:
    notion.pages.create(
        parent={"database_id": NOTION_EVENTS_DB},
        properties={
            "Titre":                   {"title": [{"text": {"content": subject[:100]}}]},
            "Date Newsletter envoyée": {"date":  {"start": send_date}},
        },
    )


def process_account(account: dict, notion: NotionClient) -> None:
    label  = account["label"]
    print(f"\nConnexion IMAP {account['email']} ({account['server']})...")

    try:
        imap = imaplib.IMAP4_SSL(account["server"], 993)
        imap.login(account["email"], account["password"])
    except imaplib.IMAP4.error as e:
        print(f"  ERREUR connexion : {e}")
        return

    folder = account["sent_folder"]
    status, _ = imap.select(f'"{folder}"', readonly=True)
    if status != "OK":
        print(f"  ERREUR ouverture dossier '{folder}'")
        imap.logout()
        return

    since = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%d-%b-%Y")
    status, data = imap.search(None, f"SINCE {since}")
    if status != "OK" or not data[0]:
        print(f"  Aucun email dans les {DAYS_BACK} derniers jours")
        imap.close(); imap.logout()
        return

    msg_ids = data[0].split()
    print(f"  {len(msg_ids)} email(s) envoyés trouvés ({DAYS_BACK}j)")

    created = 0
    for msg_id in msg_ids:
        status, raw = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (TO CC BCC SUBJECT DATE)])")
        if status != "OK":
            continue
        msg = emaillib.message_from_bytes(raw[0][1])

        nb = count_recipients(msg)
        if nb <= MIN_RECIPIENTS:
            continue

        subject   = decode_subject(msg.get("Subject", "(sans sujet)"))
        send_date = parse_send_date(msg)

        print(f"  [{label}] {subject[:60]} ({nb} dest.) → {send_date}")

        if newsletter_exists(notion, subject):
            print(f"    → Déjà enregistré")
            continue

        create_newsletter_event(notion, subject, send_date)
        print(f"    → Créé")
        created += 1

    imap.close()
    imap.logout()
    print(f"  {created} newsletter(s) créée(s)")


def main():
    notion = NotionClient(auth=os.environ["NOTION_API_KEY"])
    for account in ACCOUNTS:
        process_account(account, notion)
    print("\nTerminé.")


if __name__ == "__main__":
    main()
