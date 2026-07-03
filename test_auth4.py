import os, requests, base64
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'

# Basic auth: email:apikey
for email in ['contact@chloeludmann.fr', 'contact@sophieboutemy.com']:
    creds = base64.b64encode(f'{email}:{key}'.encode()).decode()
    r = requests.get(f'{base}/Boxes', headers={'Authorization': f'Basic {creds}', 'Accept': 'application/json'})
    print(f'Basic({email}) -> {r.status_code}: {r.text[:200]}')

# Peut-etre que /Account/token accepte un champ ApiKey separe (pas Password)
for body in [
    {'ApiKey': key, 'Email': 'contact@chloeludmann.fr'},
    {'ApiKey': key, 'Email': 'contact@sophieboutemy.com'},
    {'Key': key},
    {'Token': key},
]:
    r = requests.post(f'{base}/Account/token', json=body)
    print(f'{list(body.keys())} -> {r.status_code}: {r.text[:200]}')
