import requests, os
from dotenv import load_dotenv

load_dotenv()
r = requests.get(
    "https://us22.api.mailchimp.com/3.0/ping",
    auth=("key", os.environ["MAILCHIMP_API_KEY"]),
)
print(r.status_code, r.text)
