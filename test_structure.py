import os, requests, base64, json
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'
auth = ('contact@chloeludmann.fr', key)

# Structure complete de la premiere box
r = requests.get(f'{base}/Boxes', auth=auth)
boxes = r.json()
print(f'Nb boxes: {len(boxes)}')
if boxes:
    print('=== Cles d une box ===')
    print(json.dumps(boxes[0], indent=2, ensure_ascii=False)[:2000])

# Structure des transaction entries de la premiere box
box_id = boxes[0].get('Id') or boxes[0].get('id') if boxes else None
if box_id:
    r2 = requests.get(f'{base}/Boxes/BoxTransactionBatchEntries/{box_id}', auth=auth)
    print(f'\n=== BoxTransactionBatchEntries (status {r2.status_code}) ===')
    print(json.dumps(r2.json(), indent=2, ensure_ascii=False)[:2000] if r2.ok else r2.text[:500])
