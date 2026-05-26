"""
Génère un nouveau token OAuth Gmail permanent (mode headless).
Affiche une URL à ouvrir dans le navigateur, puis demande de coller l'URL de redirection.
"""
import os
import sys
from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import Flow

SCOPES      = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_OUT   = os.path.join(os.path.dirname(__file__), "token.json")

flow = Flow.from_client_secrets_file(
    CREDENTIALS,
    scopes=SCOPES,
    redirect_uri="http://localhost",
)

auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

print("\nOuvre cette URL dans ton navigateur :\n")
print(auth_url)
print("\nAprès avoir autorisé l'accès, le navigateur va essayer d'aller sur http://localhost")
print("et afficher une erreur — c'est normal.")
print("Copie l'URL complète depuis la barre d'adresse et colle-la ici.\n")

redirected_url = input("URL complète : ").strip()

parsed = urlparse(redirected_url)
code   = parse_qs(parsed.query).get("code", [None])[0]
if not code:
    print("Erreur : code introuvable dans l'URL.")
    sys.exit(1)

flow.fetch_token(code=code)
creds = flow.credentials

with open(TOKEN_OUT, "w") as f:
    f.write(creds.to_json())

print(f"\nToken sauvegardé : {TOKEN_OUT}")
print(f"Expiry            : {creds.expiry}")
print(f"Refresh token     : {'oui' if creds.refresh_token else 'NON — relancer avec prompt=consent'}")
