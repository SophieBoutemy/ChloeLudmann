#!/usr/bin/env python3
# OAuth manuel pur : requests + http.server, zero google-auth-oauthlib.
import os, sys, json, urllib.parse, requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

_DIR          = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE    = os.path.join(_DIR, '..', 'credentials.json')
TOKEN_FILE    = os.path.join(_DIR, '..', 'token.json')

SCOPES        = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive.file',
]
REDIRECT_URI   = 'http://localhost:8080/'
AUTH_ENDPOINT  = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'

with open(CREDS_FILE) as f:
    raw = json.load(f)
cfg           = raw.get('web') or raw.get('installed')
CLIENT_ID     = cfg['client_id']
CLIENT_SECRET = cfg['client_secret']

# 1. Construire l URL sans code_challenge
auth_url = AUTH_ENDPOINT + '?' + urllib.parse.urlencode({
    'response_type': 'code',
    'client_id':     CLIENT_ID,
    'redirect_uri':  REDIRECT_URI,
    'scope':         ' '.join(SCOPES),
    'access_type':   'offline',
    'prompt':        'consent',
})

print('\nOuvre cette URL dans ton navigateur :')
print(auth_url)
print('\nEn attente du callback sur http://localhost:8080 ...')
sys.stdout.flush()

# 2. Serveur HTTP minimal pour capturer le code
captured = {}

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence access logs

    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        if 'code' in params:
            captured['code'] = params['code'][0]
            captured['error'] = None
        else:
            captured['code'] = None
            captured['error'] = params.get('error', ['unknown'])[0]
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        msg = '<h2>Autorisation recue. Tu peux fermer cet onglet.</h2>' if captured.get('code') else '<h2>Erreur : ' + str(captured.get('error')) + '</h2>'
        self.wfile.write(msg.encode())
        # arreter le serveur apres la premiere requete
        self.server._done = True

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

server = HTTPServer(('127.0.0.1', 8080), _Handler)
server._done = False
while not server._done:
    server.handle_request()

code = captured.get('code')
if not code:
    print('Erreur OAuth :', captured.get('error'))
    sys.exit(1)

print('Code recu, echange en cours...')
sys.stdout.flush()

# 3. Echanger le code contre un token
resp = requests.post(TOKEN_ENDPOINT, data={
    'code':          code,
    'client_id':     CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'redirect_uri':  REDIRECT_URI,
    'grant_type':    'authorization_code',
})

if not resp.ok:
    print('Erreur echange token :', resp.status_code, resp.text)
    sys.exit(1)

tok = resp.json()

expiry = datetime.now(timezone.utc) + timedelta(seconds=tok.get('expires_in', 3600))

# 4. Sauvegarder au format attendu par google.oauth2.credentials.Credentials
token_json = {
    'token':         tok['access_token'],
    'refresh_token': tok.get('refresh_token'),
    'token_uri':     TOKEN_ENDPOINT,
    'client_id':     CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'scopes':        SCOPES,
    'expiry':        expiry.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z',
}

with open(TOKEN_FILE, 'w') as f:
    json.dump(token_json, f, indent=2)

print('token.json sauvegarde.')
print('Tu peux maintenant lancer factures.py')