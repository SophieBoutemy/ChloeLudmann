import requests, os
from dotenv import load_dotenv

load_dotenv()

key = os.environ["MAILCHIMP_API_KEY"]
dc  = key.split("-")[-1]
print(f"DC: {dc}")
print(f"Key: {key[:8]}...")

r = requests.get(
    f"https://{dc}.api.mailchimp.com/3.0/campaigns",
    auth=("anystring", key),
    params={"status": "sent", "count": 1},
    timeout=30,
)
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:500]}")
