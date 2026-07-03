import os, requests
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'

for label, body in [
    ('ApiKey only',    {'ApiKey': key}),
    ('apiKey only',    {'apiKey': key}),
    ('email+apikey',   {'Email': '', 'ApiKey': key}),
]:
    r = requests.post(f'{base}/Account/token', json=body)
    print(f'{label} -> {r.status_code}: {r.text[:300]}')

r = requests.get(f'{base}/Boxes', headers={'X-API-Key': key, 'Accept': 'application/json'})
print(f'X-API-Key header -> {r.status_code}: {r.text[:200]}')

r = requests.get(f'{base}/Boxes', params={'apiKey': key}, headers={'Accept': 'application/json'})
print(f'?apiKey param -> {r.status_code}: {r.text[:200]}')
