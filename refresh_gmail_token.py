#!/usr/bin/env python3
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES      = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_OUT   = os.path.join(os.path.dirname(__file__), "token.json")

flow  = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, scopes=SCOPES)
creds = flow.run_local_server(port=8080, open_browser=False, access_type="offline", prompt="consent")

with open(TOKEN_OUT, "w") as f:
    f.write(creds.to_json())

print(f"\nToken sauvegarde : {TOKEN_OUT}")
print(f"Expiry            : {creds.expiry}")
print(f"Refresh token     : {'oui' if creds.refresh_token else 'NON — relancer avec prompt=consent'}")
