import os, requests, json
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['NOTION_API_KEY']
headers = {'Authorization': f'Bearer {key}', 'Notion-Version': '2022-06-28'}
r = requests.get('https://api.notion.com/v1/databases/345afa74cfc9802ba2b9ecfc5c197996', headers=headers)
db = r.json()
print('=== CLIENTS DB ===')
for name, prop in db.get('properties', {}).items():
    ptype = prop['type']
    print(f'  {name!r}: {ptype}')
r2 = requests.get('https://api.notion.com/v1/databases/35eafa74cfc980d092d0e80644bd6be7', headers=headers)
db2 = r2.json()
print('=== EVENEMENTS DB ===')
for name, prop in db2.get('properties', {}).items():
    ptype = prop['type']
    print(f'  {name!r}: {ptype}')
