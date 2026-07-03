import os, requests
from dotenv import load_dotenv
from notion_client import Client as NotionClient

load_dotenv()

MAILCHIMP_API_KEY = os.environ["MAILCHIMP_API_KEY"]
NOTION_EVENTS_DB  = os.environ["NOTION_EVENTS_DATABASE_ID"]

DC       = MAILCHIMP_API_KEY.split("-")[-1]
BASE_URL = f"https://{DC}.api.mailchimp.com/3.0"
AUTH     = ("anystring", MAILCHIMP_API_KEY)


def get_sent_campaigns() -> list[dict]:
    campaigns = []
    offset = 0
    count  = 200
    while True:
        r = requests.get(
            f"{BASE_URL}/campaigns",
            auth=AUTH,
            params={
                "status": "sent",
                "count":  count,
                "offset": offset,
                "fields": "campaigns.id,campaigns.settings.subject_line,campaigns.send_time,total_items",
            },
            timeout=30,
        )
        r.raise_for_status()
        data  = r.json()
        batch = data.get("campaigns", [])
        campaigns.extend(batch)
        if len(campaigns) >= data.get("total_items", 0) or not batch:
            break
        offset += count
    return campaigns


def campaign_exists(notion: NotionClient, subject: str) -> bool:
    r = notion.databases.query(
        database_id=NOTION_EVENTS_DB,
        filter={"property": "Titre", "title": {"equals": subject[:100]}},
    )
    return bool(r.get("results"))


def create_campaign_event(notion: NotionClient, subject: str, send_date: str) -> None:
    notion.pages.create(
        parent={"database_id": NOTION_EVENTS_DB},
        properties={
            "Titre":                   {"title": [{"text": {"content": subject[:100]}}]},
            "Date Newsletter envoyée": {"date":  {"start": send_date}},
        },
    )


def main():
    notion = NotionClient(auth=os.environ["NOTION_API_KEY"])

    print("Récupération des campagnes Mailchimp...")
    campaigns = get_sent_campaigns()
    print(f"  {len(campaigns)} campagne(s) envoyée(s) trouvée(s)")

    created = 0
    for c in campaigns:
        subject   = c.get("settings", {}).get("subject_line", "(sans sujet)").strip()
        send_time = c.get("send_time", "")
        if not send_time:
            continue
        send_date = send_time[:10]  # YYYY-MM-DD

        print(f"  {subject[:60]}  →  {send_date}")

        if campaign_exists(notion, subject):
            print(f"    → Déjà enregistré")
            continue

        create_campaign_event(notion, subject, send_date)
        print(f"    → Créé")
        created += 1

    print(f"\n{created} entrée(s) créée(s). Terminé.")


if __name__ == "__main__":
    main()
