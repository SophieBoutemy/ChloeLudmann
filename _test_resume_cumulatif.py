"""Test du résumé cumulatif sur une fiche existante."""
import os, sys
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv(os.path.expanduser("~/automations/.env"))
notion = Client(auth=os.environ["NOTION_API_KEY"])

DB = "35eafa74cfc980d092d0e80644bd6be7"

MOIS_FR = ["janvier","février","mars","avril","mai","juin",
           "juillet","août","septembre","octobre","novembre","décembre"]

def format_entry(date_mail, resume):
    if date_mail:
        try:
            dt = datetime.strptime(date_mail, "%Y-%m-%d")
            label = f"{dt.day} {MOIS_FR[dt.month-1]} {dt.year}"
        except ValueError:
            label = date_mail
        return f"{label} — {resume}"
    return resume

# Trouver une fiche avec Résumé du mail non vide
results = notion.databases.query(
    database_id=DB,
    filter={"property": "Résumé du mail", "rich_text": {"is_not_empty": True}},
    page_size=1,
)

pages = results.get("results", [])
if not pages:
    print("Aucune fiche avec Résumé du mail non vide.")
    sys.exit(0)

page = pages[0]
page_id = page["id"]
titre_parts = page["properties"].get("Titre", {}).get("title", [])
titre = titre_parts[0]["plain_text"] if titre_parts else "(sans titre)"

rt = page["properties"].get("Résumé du mail", {}).get("rich_text", [])
existing = rt[0]["plain_text"] if rt else ""

print(f"Fiche : {titre}")
print(f"ID    : {page_id}")
print(f"\n--- Contenu actuel de 'Résumé du mail' ---")
print(existing or "(vide)")
print("---")

# Simuler l'ajout d'une nouvelle entrée
new_entry = format_entry("2026-05-26", "Test résumé cumulatif — vérification du format sans bold.")
combined = f"{new_entry}\n\n{existing}".strip() if existing else new_entry

print(f"\n--- Résultat après ajout ---")
print(combined[:500])
print("---")

# Écrire dans Notion
notion.pages.update(
    page_id=page_id,
    properties={"Résumé du mail": {"rich_text": [{"text": {"content": combined[:2000]}}]}}
)
print("\nEcrit dans Notion.")

# Relire pour confirmer
page2 = notion.pages.retrieve(page_id=page_id)
rt2 = page2["properties"].get("Résumé du mail", {}).get("rich_text", [])
readback = rt2[0]["plain_text"] if rt2 else ""
print(f"\n--- Relecture depuis Notion ---")
print(readback[:500])
print("---")
print("\nOK — format cumulatif confirmé." if readback.startswith("26 mai 2026 —") else "ATTENTION — format inattendu.")
