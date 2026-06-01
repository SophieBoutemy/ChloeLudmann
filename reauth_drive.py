import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file"
]

flow = InstalledAppFlow.from_client_secrets_file(
    "/home/ubuntu/automations/credentials.json", SCOPES)
creds = flow.run_local_server(port=8080, open_browser=False)

with open("/home/ubuntu/automations/token.json", "w") as f:
    f.write(creds.to_json())
print("Token sauvegarde avec scopes:", creds.scopes)