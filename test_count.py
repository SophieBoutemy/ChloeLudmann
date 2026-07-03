import os, requests
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['NOTION_API_KEY']
headers = {'Authorization': 'Bearer ' + key, 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'}

# Recupere toutes les pages (pagination)
all_pages = []
cursor = None
while True:
    body = {'page_size': 100}
    if cursor:
        body['start_cursor'] = cursor
    r = requests.post('https://api.notion.com/v1/databases/35eafa74cfc980d092d0e80644bd6be7/query', headers=headers, json=body)
    data = r.json()
    all_pages.extend(data.get('results', []))
    if not data.get('has_more'):
        break
    cursor = data.get('next_cursor')

print('Total entrees:', len(all_pages))
print('5 premieres (titre):')
for p in all_pages[:5]:
    props = p.get('properties', {})
    titre_prop = props.get('Titre', {})
    titre = ''
    if titre_prop.get('title'):
        titre = titre_prop['title'][0]['plain_text'] if titre_prop['title'] else '(sans titre)'
    print(' -', titre or '(sans titre)')
