import os, requests
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'

for email in ['contact@chloeludmann.fr', 'contact@sophieboutemy.com']:
    r = requests.post(f'{base}/Account/token', json={'Email': email, 'Password': key})
    print(f'{email} -> {r.status_code}: {r.text[:300]}')

# Essai avec le token dans Authorization header (format alternatif)
r = requests.get(f'{base}/Boxes', headers={'Authorization': f'ApiKey {key}', 'Accept': 'application/json'})
print(f'ApiKey header -> {r.status_code}')

r = requests.get(f'{base}/Boxes', headers={'Authorization': key, 'Accept': 'application/json'})
print(f'Raw key header -> {r.status_code}')
