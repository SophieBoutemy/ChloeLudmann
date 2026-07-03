import os, requests
from dotenv import load_dotenv
from collections import defaultdict
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['NOTION_API_KEY']
headers = {'Authorization': 'Bearer ' + key, 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'}

pages, cursor = [], None
while True:
    body = {'page_size': 100}
    if cursor: body['start_cursor'] = cursor
    r = requests.post('https://api.notion.com/v1/databases/35eafa74cfc980d092d0e80644bd6be7/query', headers=headers, json=body)
    data = r.json()
    pages.extend(data.get('results', []))
    if not data.get('has_more'): break
    cursor = data.get('next_cursor')

by_client = defaultdict(list)
for p in pages:
    rels = p.get('properties', {}).get('Client', {}).get('relation', [])
    cid = rels[0]['id'] if rels else ''
    title_parts = p.get('properties', {}).get('Titre', {}).get('title', [])
    titre = title_parts[0]['plain_text'] if title_parts else '(vide)'
    by_client[cid].append((p['id'], titre))

multi = {cid: evts for cid, evts in by_client.items() if len(evts) > 1}
print(f'Total pages: {len(pages)}')
print(f'Clients avec plusieurs evenements: {len(multi)}')
for cid, evts in list(multi.items())[:5]:
    print(f'  client {cid[:8]}...')
    for pid, t in evts:
        print(f'    [{pid[:8]}] {t}')
