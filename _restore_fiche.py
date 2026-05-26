import os
from dotenv import load_dotenv
from notion_client import Client
load_dotenv(os.path.expanduser("~/automations/.env"))
notion = Client(auth=os.environ["NOTION_API_KEY"])
notion.pages.update(
    page_id="35fafa74-cfc9-81b8-ace7-fc6cdcfce6e4",
    properties={"Résumé du mail": {"rich_text": [{"text": {"content": "Clémantine, élève de Domitile, demande à s'inscrire au cours de chant du 4 mai s'il reste de la place."}}]}}
)
print("Restauré.")
