from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json, os

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE  = os.path.join(os.path.dirname(__file__), "token.json")

flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
auth_url, _ = flow.authorization_url(prompt="consent")
print(f"\nOuvre cette URL dans ton navigateur :\n{auth_url}\n")
code = input("Colle le code d'autorisation : ").strip()
flow.fetch_token(code=code)
creds = flow.credentials

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())
print(f"\ntoken.json sauvegardé.")

service = build("gmail", "v1", credentials=creds)
profile = service.users().getProfile(userId="me").execute()
print(f"Connecté : {profile['emailAddress']} ({profile['messagesTotal']} messages)")
