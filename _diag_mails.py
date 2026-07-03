"""Diagnostique pourquoi des mails spécifiques ont été ignorés."""
import os, imaplib, email, json
from email.header import decode_header
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic

load_dotenv(os.path.expanduser("~/automations/.env"))

IMAP_HOST = "ssl0.ovh.net"
IMAP_USER = os.environ["IMAP_EMAIL"]
IMAP_PASS = os.environ["IMAP_PASSWORD"]
DAYS_BACK = 2
TARGET_FROM = "sophieboutemy"  # filtre souple

CLASSIFIER_PROMPT = """\
Sujet : {subject}
Message : {body}

Tu analyses les emails reçus pour un professeur de chant.
1. Détermine si cet email concerne une absence, une annulation, un retard ou une demande de rattrapage de cours :
- true = UNIQUEMENT si c'est un élève ou parent qui signale une absence, annule un cours, prévient d'un retard ou demande un rattrapage
- false = tout le reste (spam, newsletter, facture, question générale, prise de contact initiale)
2. Si true, extrais :
- prenom : prénom de l'élève (ou de l'expéditeur si non précisé)
- nom : nom de famille
- date_concernee : date du cours concerné au format YYYY-MM-DD (null si non précisée)
- type_demande : une seule valeur parmi : absence / annulation / retard / rattrapage
- resume_message : résumé en 1-2 phrases
- date_mail : date d'envoi du mail au format YYYY-MM-DD
Règles : réponse JSON pur, commence par {{ finit par }}, jamais de ```json\
"""

def decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            result.append(part)
    return " ".join(result)

def extract_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
    return ""

since_date = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%d-%b-%Y")

print(f"Connexion IMAP {IMAP_USER}...")
with imaplib.IMAP4_SSL(IMAP_HOST, 993) as imap:
    imap.login(IMAP_USER, IMAP_PASS)
    imap.select("INBOX")
    _, data = imap.search(None, f"SINCE {since_date}")
    all_ids = data[0].split()
    print(f"{len(all_ids)} email(s) dans la fenêtre {DAYS_BACK}j\n")

    found = []
    for uid in all_ids:
        _, msg_data = imap.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        from_str = decode_str(msg.get("From", ""))
        if TARGET_FROM.lower() in from_str.lower():
            found.append({
                "uid": uid,
                "subject": decode_str(msg.get("Subject", "")),
                "from": from_str,
                "date": msg.get("Date", ""),
                "body": extract_body(msg),
            })

print(f"{len(found)} email(s) de '{TARGET_FROM}' trouvé(s) :\n")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

for em in found:
    print(f"--- Email ---")
    print(f"  De      : {em['from']}")
    print(f"  Date    : {em['date']}")
    print(f"  Sujet   : {em['subject']}")
    print(f"  Corps   : {em['body'][:300]!r}")

    prompt = CLASSIFIER_PROMPT.format(subject=em["subject"], body=em["body"][:3000] or "(vide)")
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_json = resp.content[0].text.strip()
    print(f"  Réponse Claude : {raw_json}")
    try:
        parsed = json.loads(raw_json[raw_json.find("{"):raw_json.rfind("}")+1])
        is_client = parsed.get("is_client", False)
        print(f"  → is_client={is_client}")
        if not is_client:
            print(f"  → IGNORÉ par Claude (is_client=false)")
        else:
            print(f"  → TRAITÉ : prenom={parsed.get('prenom')}, nom={parsed.get('nom')}, type={parsed.get('type_demande')}")
    except Exception as e:
        print(f"  → Erreur parsing JSON : {e}")
    print()
