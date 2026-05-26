import os, requests
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['NOTION_API_KEY']
headers = {'Authorization': 'Bearer ' + key, 'Notion-Version': '2022-06-28'}
r = requests.get('https://api.notion.com/v1/databases/35eafa74cfc980d092d0e80644bd6be7', headers=headers)
print('Status:', r.status_code)
if r.ok:
    db = r.json()
    print('ID    :', db['id'])
    print('Titre :', db['title'][0]['plain_text'])
    print('Acces : OK')
else:
    print(r.text[:300])
