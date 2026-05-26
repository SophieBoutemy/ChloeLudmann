import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from notion_client import Client

# Chargement des clés API
load_dotenv()

# Scopes Gmail - lecture seule
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def connecter_gmail():
    """Connexion à Gmail via OAuth"""
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES
    )
    creds = flow.run_local_server(port=0)
    return build('gmail', 'v1', credentials=creds)

def connecter_notion():
    """Connexion à Notion"""
    return Client(auth=os.getenv("NOTION_API_KEY"))

def lire_mails(service, nombre=10):
    """Récupère les derniers mails"""
    results = service.users().messages().list(
        userId='me', maxResults=nombre
    ).execute()
    return results.get('messages', [])

def main():
    print("Connexion Gmail...")
    gmail = connecter_gmail()
    print("Connexion Notion...")
    notion = connecter_notion()
    print("Lecture des mails...")
    mails = lire_mails(gmail)
    print(f"{len(mails)} mails récupérés")

def classifier_mail(client_anthropic, sujet, corps):
    """Envoie le mail à Claude pour classification"""
    message = client_anthropic.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": f"""Classifie ce mail en une seule catégorie parmi :
demande_client, reclamation, information, absence, spam, autre.
Réponds uniquement avec le nom de la catégorie, rien d'autre.

Sujet : {sujet}
Corps : {corps}"""
        }]
    )
    return message.content[0].text.strip()
if __name__ == "__main__":
    main()
