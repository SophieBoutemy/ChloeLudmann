import os, re, json, base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic

load_dotenv()

_DIR        = os.path.dirname(os.path.abspath(__file__))
GMAIL_TOKEN = os.path.join(_DIR, "token.json")
SCOPES      = ["https://www.googleapis.com/auth/gmail.readonly"]
TARGET      = "cours de chant - test 3"

_SKIP_SUBJECT = re.compile(
    r"\[spam\]|newsletter|bulletin|facture\s*n[°o]|receipt|re[çc]u\b|"
    r"votre\s+commande|livraison|exp[eé]dition|abonnement|d[eé]sabonnement|"
    r"unsubscribe|offre\s+sp[eé]ciale|promotion|soldes|\d+\s*%\s*(?:de\s+)?r[eé]duction|"
    r"votre\s+code\b|code\s+de\s+v[eé]rification|paiement\s+trait[eé]|"
    r"rappel\s+de\s+paiement",
    re.IGNORECASE,
)
_SKIP_SENDER = re.compile(
    r"noreply@|no-reply@|donotreply@|mailer-daemon@|"
    r"@paypal\.|@stripe\.|@doctolib\.|@amazon\.|@ebay\.|"
    r"@facebook\.|@instagram\.|@twitter\.|@linkedin\.",
    re.IGNORECASE,
)

CLASSIFIER_PROMPT = """\
Sujet : {subject}
Message : {body}

Tu analyses les emails reçus pour un professeur de chant.
Retourne un JSON avec exactement ces champs :
- is_client : true UNIQUEMENT si l'email concerne des cours de CHANT (élève ou prospect) : absence/annulation/retard/rattrapage d'un cours de chant, demande de renseignements sur les cours de chant, question sur les tarifs des cours, demande de cours, inscription, prise de contact pour des cours de chant — false pour tout le reste (spam, newsletter, facture, notification, immobilier, médical, personnel, hors chant)
- prenom : prénom de l'expéditeur (ou de l'élève si mentionné), null si is_client false
- nom : nom de famille, null si is_client false
- date_concernee : date du cours concerné au format YYYY-MM-DD, null si non applicable
- type_demande : une valeur parmi absence / annulation / retard / rattrapage / renseignement / tarif / demande_cours / inscription / contact — null si is_client false
- resume_message : résumé en 1-2 phrases, null si is_client false
- date_mail : date d'envoi du mail au format YYYY-MM-DD
Règles : réponse JSON pur, commence par {{ finit par }}, jamais de ```json\
"""

def get_service():
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)

def extract_body(payload):
    from html.parser import HTMLParser
    class P(HTMLParser):
        def __init__(self): super().__init__(); self._t=[]; self._s=False
        def handle_starttag(self,t,a):
            if t in ("script","style"): self._s=True
        def handle_endtag(self,t):
            if t in ("script","style"): self._s=False
            if t in ("br","p","div","tr","li"): self._t.append("\n")
        def handle_data(self,d):
            if not self._s: self._t.append(d)
        def get_text(self): return re.sub(r"\n{3,}","\n\n","".join(self._t)).strip()

    mime = payload.get("mimeType","")
    data = payload.get("body",{}).get("data","")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    if mime == "text/html" and data:
        p = P(); p.feed(base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")); return p.get_text()
    plain = html = None
    for part in payload.get("parts", []):
        t = extract_body(part)
        if t and not plain: plain = t
    return plain or ""

service = get_service()
since = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")

print(f"=== Recherche de '{TARGET}' dans Gmail (24h) ===\n")

# 1. Chercher dans inbox
result = service.users().messages().list(
    userId="me",
    q=f'after:{since} subject:"{TARGET}"',
    maxResults=10
).execute()
msgs = result.get("messages", [])
print(f"Résultats Gmail (subject:'{TARGET}') : {len(msgs)} message(s)\n")

if not msgs:
    print(">>> Mail introuvable via search Gmail — vérifier s'il est dans inbox ou ailleurs")
    # Chercher sans in:inbox
    result2 = service.users().messages().list(
        userId="me",
        q=f'after:{since} subject:"{TARGET}"',
        maxResults=10
    ).execute()
    print(f"Sans filtre in:inbox : {len(result2.get('messages', []))} message(s)")
else:
    for msg_meta in msgs:
        msg_id = msg_meta["id"]
        full = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        subj   = headers.get("Subject", "")
        sender = headers.get("From", "")
        date   = headers.get("Date", "")
        labels = full.get("labelIds", [])
        body   = extract_body(full["payload"])

        print(f"ID      : {msg_id}")
        print(f"Sujet   : {subj}")
        print(f"De      : {sender}")
        print(f"Date    : {date}")
        print(f"Labels  : {labels}")
        print(f"Corps   : {body[:300]!r}")
        print()

        skip_subj = bool(_SKIP_SUBJECT.search(subj))
        skip_send = bool(_SKIP_SENDER.search(sender))
        print(f"Filtre _SKIP_SUBJECT : {skip_subj}")
        print(f"Filtre _SKIP_SENDER  : {skip_send}")
        print(f"→ Passe le filtre metadata : {not skip_subj and not skip_send}")
        print()

        if not skip_subj and not skip_send:
            print("=== Appel Claude ===")
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": CLASSIFIER_PROMPT.format(subject=subj, body=body[:3000])}],
            )
            raw = resp.content[0].text.strip()
            print(f"JSON brut Claude :\n{raw}")
            try:
                parsed = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
                print(f"\nParsé : {json.dumps(parsed, ensure_ascii=False, indent=2)}")
            except Exception as e:
                print(f"Erreur parsing : {e}")
