import os, requests, json
from dotenv import load_dotenv
from collections import Counter
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'
auth = ('contact@chloeludmann.fr', key)
r = requests.get(f'{base}/Boxes/BoxTransactionBatchEntries/435d57fe-5093-49ab-bb21-89f039d98639', auth=auth)
entries = r.json()
statuses = Counter(e['TransactionStatus'] for e in entries)
print(f'TransactionStatus values: {dict(statuses)}')
e = entries[0]
date_keys = [k for k in e if 'date' in k.lower() or 'Date' in k]
print(f'Date fields on entry: {date_keys}')
for k in date_keys:
    print(f'  {k} = {e.get(k)}')
contact_id = entries[0]['ContactId']
r2 = requests.get(f'{base}/Contacts/ById/{contact_id}', auth=auth)
print('\\n=== Contact structure ===')
print(json.dumps(r2.json(), indent=2, ensure_ascii=False)[:1500])
