import os
from dotenv import load_dotenv
from notion_client import Client
load_dotenv(os.path.expanduser("~/automations/.env"))
n = Client(auth=os.environ["NOTION_API_KEY"])
db = n.databases.retrieve(database_id="35eafa74cfc980d092d0e80644bd6be7")
print("Propriétés DB Events:")
for name, prop in db["properties"].items():
    print(f"  {prop['type']:<20} {name!r}")

# Aussi vérifier une page pour voir les relations Client
r = n.databases.query(database_id="35eafa74cfc980d092d0e80644bd6be7", page_size=3)
print(f"\n{len(r['results'])} premières fiches:")
for page in r["results"]:
    titre = page["properties"].get("Titre", {}).get("title", [])
    titre_val = titre[0]["plain_text"] if titre else "(vide)"
    rels = page["properties"].get("Client", {}).get("relation", [])
    print(f"  Titre={titre_val!r}  Client_rels={len(rels)}")
