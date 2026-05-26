import os
import json
import base64
import anthropic

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from notion_client import Client as NotionClient

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY     = os.environ["NOTION_API_KEY"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

_DIR               = os.path.dirname(os.path.abspath(__file__))
GMAIL_SCOPES       = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_CREDENTIALS  = os.path.join(_DIR, "credentials.json")
GMAIL_TOKEN        = os.path.join(_DIR, "token.json")

CLAUDE_MODEL       = "claude-haiku-4-5-20251001"

CLASSIFIER_PROMPT = """\
Sujet : {subject}
Message : {body}

Analyse cet email.
1. Détermine si c'est un email client (demande, absence, inscription, question) :
- true = UNIQUEMENT si c'est une vraie personne qui contacte directement pour une demande personnelle, une absence, une inscription à un cours ou une question sur un service
- false = tout le reste : marketing, spam, newsletter, notification automatique, Paypal, Doctolib, livraison, réseaux sociaux, satisfaction, sondage, confirmation automatique
2. Extrais si présent : Prénom, Nom, Téléphone, Date absence (YYYY-MM-DD), Résumé message, Date du mail (YYYY-MM-DD)
Règles : réponse JSON pur, commence par {{ finit par }}, jamais de ```json\
"""

# ── Gmail ─────────────────────────────────────────────────────────────────────

def get_gmail_service():
    if not os.path.exists(GMAIL_TOKEN):
        raise FileNotFoundError(f"token.json introuvable — relance auth_gmail.py pour générer le token.")
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(GMAIL_TOKEN, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("Token expiré sans refresh_token — relance auth_gmail.py.")
    return build("gmail", "v1", credentials=creds)


def fetch_unread_emails(service, max_results=20):
    result = service.users().messages().list(
        userId="me", labelIds=["INBOX"], q="is:unread", maxResults=max_results
    ).execute()
    messages = result.get("messages", [])

    emails = []
    for msg in messages:
        full = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        body = extract_body(full["payload"])
        emails.append({
            "id":      msg["id"],
            "subject": headers.get("Subject", ""),
            "from":    headers.get("From", ""),
            "date":    headers.get("Date", ""),
            "body":    body,
        })
    return emails


def extract_body(payload):
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        # fallback sur la première part
        return extract_body(payload["parts"][0])
    data = payload.get("body", {}).get("data", "")
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore") if data else ""

# ── Claude ────────────────────────────────────────────────────────────────────

def classify_email(email: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = CLASSIFIER_PROMPT.format(subject=email["subject"], body=email["body"][:3000])

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    return json.loads(raw)

# ── Notion ────────────────────────────────────────────────────────────────────

def notion_find_contact(notion: NotionClient, prenom: str, nom: str):
    results = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "and": [
                {"property": "Prénom", "rich_text": {"equals": prenom}},
                {"property": "Nom",    "rich_text": {"equals": nom}},
            ]
        },
    )
    pages = results.get("results", [])
    return pages[0]["id"] if pages else None


def notion_properties(data: dict) -> dict:
    props = {}

    def text(val):
        return {"rich_text": [{"text": {"content": val or ""}}]}

    def date(val):
        return {"date": {"start": val}} if val else {"date": None}

    if data.get("prenom"):
        props["Prénom"] = text(data["prenom"])
    if data.get("nom"):
        props["Nom"] = text(data["nom"])
    if data.get("telephone"):
        props["Téléphone"] = {"phone_number": data["telephone"]}
    if data.get("resume_message"):
        props["Résumé message"] = text(data["resume_message"])
    if data.get("date_mail"):
        props["Date du mail"] = date(data["date_mail"])
    if data.get("date_absence"):
        props["Date absence"] = date(data["date_absence"])

    props["Type de contact"] = {"select": {"name": "email"}}
    return props


def upsert_notion(data: dict):
    notion = NotionClient(auth=NOTION_API_KEY)
    prenom = data.get("prenom", "")
    nom    = data.get("nom", "")
    props  = notion_properties(data)

    page_id = notion_find_contact(notion, prenom, nom) if prenom and nom else None

    if page_id:
        notion.pages.update(page_id=page_id, properties=props)
        print(f"  → Notion mis à jour : {prenom} {nom}")
    else:
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=props,
        )
        print(f"  → Notion créé : {prenom} {nom}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Connexion Gmail...")
    service = get_gmail_service()

    print("Récupération des emails non lus...")
    emails = fetch_unread_emails(service)
    print(f"{len(emails)} email(s) trouvé(s).\n")

    for email in emails:
        print(f"Analyse : {email['subject'][:60]}")
        try:
            result = classify_email(email)
        except json.JSONDecodeError as e:
            print(f"  ✗ JSON invalide : {e}")
            continue

        if result.get("is_client"):
            upsert_notion(result)
        else:
            print("  → Ignoré (non-client)")

    print("\nTerminé.")


if __name__ == "__main__":
    main()
