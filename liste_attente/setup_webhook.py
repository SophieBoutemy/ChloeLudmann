#!/usr/bin/env python3
"""
Enregistre un webhook Calendly sur /calendly pour l'événement invitee.canceled.
Usage : python setup_webhook.py
"""
import base64
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
VPS_URL        = os.environ["VPS_URL"].rstrip("/")

HEADERS = {
    "Authorization": f"Bearer {CALENDLY_TOKEN}",
    "Content-Type": "application/json",
}

CALENDLY_API = "https://api.calendly.com"


def decode_jwt_payload(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def get_user_uri() -> str:
    payload = decode_jwt_payload(CALENDLY_TOKEN)
    return f"{CALENDLY_API}/users/{payload['user_uuid']}"


def get_org_uri_from_profile() -> str | None:
    """Récupère l'org URI via /users/me (nécessite users:read)."""
    r = requests.get(f"{CALENDLY_API}/users/me", headers=HEADERS)
    if r.ok:
        return r.json().get("resource", {}).get("current_organization")
    return None


def create_webhook(org_uri: str, user_uri: str) -> dict:
    r = requests.post(
        f"{CALENDLY_API}/webhook_subscriptions",
        headers=HEADERS,
        json={
            "url":          f"{VPS_URL}/calendly",
            "events":       ["invitee.canceled"],
            "organization": org_uri,
            "user":         user_uri,
            "scope":        "user",
        },
    )
    r.raise_for_status()
    return r.json()


def list_webhooks(org_uri: str, user_uri: str) -> list:
    r = requests.get(
        f"{CALENDLY_API}/webhook_subscriptions",
        headers=HEADERS,
        params={"organization": org_uri, "user": user_uri, "scope": "user"},
    )
    r.raise_for_status()
    return r.json().get("collection", [])


def main():
    user_uri = get_user_uri()
    print(f"User URI : {user_uri}")

    # Essai 1 : org URI via /users/me
    org_uri = get_org_uri_from_profile()

    # Essai 2 : fallback user URI comme org
    if not org_uri:
        print("Impossible d'obtenir l'org via /users/me — fallback user URI...")
        org_uri = user_uri

    print(f"Org URI  : {org_uri}")

    target_url = f"{VPS_URL}/calendly"

    # Vérifie les doublons si on a une org valide
    try:
        existing = list_webhooks(org_uri, user_uri)
        for wh in existing:
            if wh.get("url") == target_url:
                print(f"Webhook déjà enregistré : {wh['uri']}")
                return
    except requests.HTTPError as e:
        print(f"Note: impossible de lister les webhooks ({e}), tentative de création directe...")

    print(f"Création du webhook sur {target_url}...")
    try:
        result = create_webhook(org_uri, user_uri)
        print(f"OK — {result['resource']['uri']}")
    except requests.HTTPError as e:
        print(f"Erreur création : {e.response.status_code}")
        print(e.response.text)
        print()
        print("Le token n'a pas les droits suffisants.")
        print("Génère un nouveau token Calendly avec les scopes : users:read webhooks:read webhooks:write")
        print("Calendly > Integrations > API & Webhooks > Personal Access Tokens")


if __name__ == "__main__":
    main()
