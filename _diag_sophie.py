"""Diagnostique les deux mails de sophie.ledoux.boutemy@gmail.com."""
import os, imaplib, email, json
from email.header import decode_header
from html.parser import HTMLParser
from datetime import datetime, timedelta
import re
from dotenv import load_dotenv
import anthropic

load_dotenv(os.path.expanduser("~/automations/.env"))

TARGET = "sophie.ledoux.boutemy@gmail.com"

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

def decode_str(v):
    if not v:
        return ""
    parts = decode_header(v)
    return " ".join(
        p.decode(c or "utf-8", errors="ignore") if isinstance(p, bytes) else p
        for p, c in parts
    )

class _HTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._t, self._s = [], False
    def handle_starttag(self, tag, _):
        if tag in ("script","style"): self._s = True
        if tag in ("br","p","div","tr","li"): self._t.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script","style"): self._s = False
    def handle_data(self, d):
        if not self._s: self._t.append(d)
    def text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self._t)).strip()

def extract_body(msg):
    html_fb = None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
            if ct == "text/html" and not html_fb:
                html_fb = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
    else:
        p = msg.get_payload(decode=True)
        if p:
            raw = p.decode(msg.get_content_charset() or "utf-8", errors="ignore")
            if msg.get_content_type() == "text/html":
                html_fb = raw
            else:
                return raw
    if html_fb:
        h = _HTML(); h.feed(html_fb); return h.text()
    return ""

since = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
with imaplib.IMAP4_SSL("ssl0.ovh.net", 993) as imap:
    imap.login(os.environ["IMAP_EMAIL"], os.environ["IMAP_PASSWORD"])
    imap.select("INBOX")
    _, data = imap.search(None, f"SINCE {since}")
    found = []
    for uid in data[0].split():
        _, md = imap.fetch(uid, "(RFC822)")
        msg = email.message_from_bytes(md[0][1])
        if TARGET in decode_str(msg.get("From", "")):
            found.append({
                "subject": decode_str(msg.get("Subject", "")),
                "from":    decode_str(msg.get("From", "")),
                "date":    msg.get("Date", ""),
                "body":    extract_body(msg),
            })

print(f"{len(found)} mail(s) de {TARGET}\n")
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

for i, em in enumerate(found, 1):
    print(f"=== Mail {i} ===")
    print(f"Sujet : {em['subject']}")
    print(f"Date  : {em['date']}")
    print(f"Corps :\n{em['body'][:600]}")
    print()
    prompt = CLASSIFIER_PROMPT.format(subject=em["subject"], body=em["body"][:3000] or "(vide)")
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    print(f"Réponse Claude : {raw}")
    try:
        parsed = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        print(f"→ is_client = {parsed.get('is_client')}")
        if not parsed.get("is_client"):
            print("→ RAISON : Claude juge que ce n'est pas une absence/annulation/retard/rattrapage")
        else:
            print(f"→ type={parsed.get('type_demande')}, resume={parsed.get('resume_message')}")
    except Exception as e:
        print(f"→ Erreur JSON : {e}")
    print()
