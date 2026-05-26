import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from notion_client import Client

load_dotenv(os.path.expanduser("~/automations/.env"))

NOTION_API_KEY  = os.environ["NOTION_API_KEY"]
EVENTS_DB       = "35eafa74cfc980d092d0e80644bd6be7"
BACKUP_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
RETENTION_DAYS  = 30


def export_database(notion: Client, database_id: str) -> list:
    pages, cursor = [], None
    while True:
        r = notion.databases.query(
            database_id=database_id,
            **{"start_cursor": cursor} if cursor else {},
        )
        pages.extend(r.get("results", []))
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
    return pages


def cleanup_old_backups(backup_dir: str, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0
    for fname in os.listdir(backup_dir):
        if not fname.startswith("backup_eleves_") or not fname.endswith(".json"):
            continue
        fpath = os.path.join(backup_dir, fname)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
        if mtime < cutoff:
            os.remove(fpath)
            print(f"  Supprimé : {fname}")
            deleted += 1
    return deleted


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    notion = Client(auth=NOTION_API_KEY)

    date_str  = datetime.now().strftime("%Y-%m-%d")
    out_path  = os.path.join(BACKUP_DIR, f"backup_eleves_{date_str}.json")

    print(f"Export base Élèves ({EVENTS_DB})...")
    pages = export_database(notion, EVENTS_DB)
    print(f"  {len(pages)} fiche(s) exportée(s)")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2, default=str)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"  Sauvegardé : {out_path} ({size_kb} Ko)")

    deleted = cleanup_old_backups(BACKUP_DIR, RETENTION_DAYS)
    if deleted:
        print(f"  {deleted} ancien(s) backup(s) supprimé(s) (>{RETENTION_DAYS}j)")

    print("Terminé.")


if __name__ == "__main__":
    main()
