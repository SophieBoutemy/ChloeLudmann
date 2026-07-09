#!/usr/bin/env python3
import os
import base64
import json
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

NOTION_API_KEY = os.environ["NOTION_API_KEY"]
CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
ELEVES_DB = "35eafa74cfc980d092d0e80644bd6be7"

headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"}
r = requests.get(f"https://api.notion.com/v1/databases/{ELEVES_DB}", headers=headers)
db = r.json()
print("=== ELEVES DB PROPERTIES ===")
for name, prop in db.get("properties", {}).items():
    print(f"  {name!r}: {prop['type']}")

print()
print("=== CALENDLY ===")

def decode_jwt_payload(token):
    payload_b64 = token.split(".")[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))

payload = decode_jwt_payload(CALENDLY_TOKEN)
user_uri = f"https://api.calendly.com/users/{payload['user_uuid']}"
print("user_uri:", user_uri)

CH = {"Authorization": f"Bearer {CALENDLY_TOKEN}"}
r2 = requests.get("https://api.calendly.com/scheduled_events", headers=CH,
                   params={"user": user_uri, "count": 2, "status": "active"})
print("scheduled_events status:", r2.status_code)
data = r2.json()
print(json.dumps(data, indent=2)[:2000])

events = data.get("collection", [])
if events:
    ev_uri = events[0]["uri"]
    r3 = requests.get(f"{ev_uri}/invitees", headers=CH, params={"count": 2})
    print()
    print("=== INVITEES SAMPLE ===")
    print(json.dumps(r3.json(), indent=2)[:2500])
