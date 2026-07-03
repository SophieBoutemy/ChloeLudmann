import os, requests
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/automations/.env')
key = os.environ['DOCAGE_API_KEY']
base = 'https://api.docage.com'

# L'email du compte Docage (a ajuster si different)
email = 'contact@sophieboutemy.com'

# Hypothese : la cle API sert de Password dans LoginDTO
r = requests.post(f'{base}/Account/token', json={'Email': email, 'Password': key})
print(f'email+apikey_as_password -> {r.status_code}: {r.text[:400]}')

# Hypothese : champ ApiKey dans le LoginDTO
r = requests.post(f'{base}/Account/token', json={'Email': email, 'Password': '', 'ApiKey': key})
print(f'email+apikey_field -> {r.status_code}: {r.text[:400]}')
