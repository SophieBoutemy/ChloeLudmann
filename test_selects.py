import os, requests, json
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['NOTION_API_KEY']
headers = {'Authorization': f'Bearer {key}', 'Notion-Version': '2022-06-28'}
r = requests.get('https://api.notion.com/v1/databases/35eafa74cfc980d092d0e80644bd6be7', headers=headers)
db = r.json()
prop = db['properties'].get('Statut contrat envoye') or db['properties'].get('Statut contrat envoye') 
# cherche la prop qui contient 'statut'
for name, p in db['properties'].items():
    if p['type'] == 'select':
        opts = [o['name'] for o in p.get('select', {}).get('options', [])]
        print(f'{name!r}: {opts}')
