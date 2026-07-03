import os
import json
import imaplib
import email
import re
import base64
import time
from email.header import decode_header
from html.parser import HTMLParser
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
from notion_client import Client as NotionClient
from notion_client.errors import RequestTimeoutError as NotionTimeout
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

# Config

ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY       = os.environ["NOTION_API_KEY"]
NOTION_EVENTS_DB = os.environ.get("NOTION_EVENTS_DATABASE_ID", "35eafa74cfc980d092d0e80644bd6be7")

_DIR          = os.path.dirname(os.path.abspath(__file__))
GMAIL_TOKEN   = os.path.join(_DIR, "token.json")
GMAIL_SCOPES  = ["https://www.googleapis.com/auth/gmail.readonly"]
PROCESSED_EMAILS_FILE = os.path.join(_DIR, "processed_emails.json")

IMAP_PORT = 993

IMAP_ACCOUNTS = [
    {
        "host":     "ssl0.ovh.net",
        "user":     os.environ.get("IMAP_EMAIL", "contact@chloeludmann.fr"),
        "password": os.environ["IMAP_PASSWORD"],
        "boite":    os.environ.get("IMAP_EMAIL", "contact@chloeludmann.fr"),
    },
    {
        "host":     "mail.infomaniak.com",
        "user":     os.environ.get("IMAP_EMAIL_WHISPER", "contact@whisper-in-the-rennes.fr"),
        "password": os.environ.get("IMAP_PASSWORD_WHISPER", ""),
        "boite":    os.environ.get("IMAP_EMAIL_WHISPER", "contact@whisper-in-the-rennes.fr"),
    },
]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
DAYS_BACK    = 2

CALENDLY_PREFIXES = ("annulé :", "nouvel événement:", "mise à jour:")

_SKIP_SUBJECT = re.compile(
    r"\[spam\]|newsletter|bulletin|facture\s*n[o°]|receipt|re[çc]u\b|"
    r"votre\s+commande|livraison|exp[eé]dition|abonnement|d[eé]sabonnement|"
    r"unsubscribe|offre\s+sp[eé]ciale|promotion|soldes|\d+\s*%\s*(?:de\s+)?r[eé]duction|"
    r"votre\s+code\b|code\s+de\s+v[eé]rification|paiement\s+trait[eé]|"
    r"rappel\s+de\s+paiement|mise\s+[àa]\s+jour\s+de\s+s[eé]curit[eé]",
    re.IGNORECASE,
)
_SKIP_SENDER = re.compile(
    r"noreply@|no-reply@|donotreply@|mailer-daemon@|"
    r"@paypal\.|@stripe\.|@doctolib\.|@amazon\.|@ebay\.|"
    r"@facebook\.|@instagram\.|@twitter\.|@linkedin\.",
    re.IGNORECASE,
)

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS_FR  = ["janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

CLASSIFIER_PROMPT = """\
Sujet : {subject}
Message : {body}

Tu analyses les emails reçus pour Chloé, professeure de chant (cours individuels, chorale, coaching vocal, projet Whisper, scènes ouvertes, ateliers).
1. Cet email est-il pertinent pour ses activités ?
- is_client = true : tout mail lié à ses activités — inscription, prise de contact, demande d'information, cours de chant, chorale, coaching vocal, Whisper, scène ouverte, atelier, absence, annulation, retard, rattrapage, question sur les tarifs ou les horaires, réponse à un mail de Chloé concernant ses cours
- is_client = false : UNIQUEMENT spam, newsletter commerciale, mail automatique (facture, livraison, sécurité, noreply), ou mail sans aucun rapport avec ces activités
2. Si is_client = true, extrais :
- prenom : prénom de l'expéditeur ou de l'élève mentionné
- nom : nom de famille
- type_demande : une valeur parmi : absence / annulation / retard / rattrapage / inscription / prise_de_contact / demande_info / chorale / coaching / whisper / scene_ouverte / atelier / autre
- resume_message : résumé en 1-2 phrases du contenu du mail
- date_mail : date d'envoi du mail au format YYYY-MM-DD
Règles : réponse JSON pur, commence par {{ finit par }}, jamais de ```json\
"""

CALENDLY_PROMPT = """\
Sujet : {subject}
Message : {body}

Cet email est une notification de calendrier (Google Calendar / Calendly) pour un cours de chant.
Extrais les informations suivantes :
- email_eleve : adresse email de l'élève (cherche dans le corps du mail, format user@domain.com)
- nom_eleve : nom complet de l'élève (souvent dans le sujet après "avec" ou en début de sujet)
- date_cours : date du cours concerné au format YYYY-MM-DD, cherche dans le sujet ET dans le corps du mail (null si absente)
- heure_cours : heure du cours au format HH:MM (24h), cherche dans le sujet ET dans le corps du mail (null si absente)
- date_mail : date d'envoi du mail au format YYYY-MM-DD
- type_evenement : "annulation" si le sujet contient "Annulé", "confirmation" si "Nouvel événement", "mise_a_jour" si "Mise à jour"
Règles : réponse JSON pur, commence par {{ finit par }}, jamais de ```json\
"""


def format_date_fr(date_str: str, heure_str: str = "") -> str:
    try:
        dt    = datetime.strptime(date_str, "%Y-%m-%d")
        label = f"{JOURS_FR[dt.weekday()]} {dt.day} {MOIS_FR[dt.month - 1]} {dt.year}"
        if heure_str:
            label += f" à {heure_str.replace(':', 'h')}"
        return label
    except (ValueError, TypeError):
        return date_str or ""


# Deduplication

def load_processed_ids() -> set:
    if os.path.exists(PROCESSED_EMAILS_FILE):
        with open(PROCESSED_EMAILS_FILE) as f:
            return set(json.load(f))
    return set()


def save_processed_id(email_key: str, processed_ids: set) -> None:
    processed_ids.add(email_key)
    with open(PROCESSED_EMAILS_FILE, "w") as f:
        json.dump(list(processed_ids), f)


def get_email_key(em: dict) -> str:
    mid = em.get("message_id", "")
    if mid:
        return mid
    uid = em["uid"]
    if isinstance(uid, bytes):
        uid = uid.decode()
    return f"{em['source']}:{em['boite']}:{uid}"


# IMAP

def decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="ignore"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="ignore"))
        else:
            result.append(part)
    return " ".join(result)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip  = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("br", "p", "div", "tr", "li"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts)).strip()


def _html_to_text(html: str) -> str:
    p = _HTMLTextExtractor()
    p.feed(html)
    return p.get_text()


def extract_imap_body(msg):
    html_fallback = None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
            if ct == "text/html" and html_fallback is None:
                charset = part.get_content_charset() or "utf-8"
                html_fallback = part.get_payload(decode=True).decode(charset, errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            raw = payload.decode(charset, errors="ignore")
            if msg.get_content_type() == "text/html":
                html_fallback = raw
            else:
                return raw
    return _html_to_text(html_fallback) if html_fallback else ""


def _fetch_imap_account(host: str, user: str, password: str, boite: str, days: int) -> list:
    since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    emails = []
    with imaplib.IMAP4_SSL(host, IMAP_PORT) as imap:
        imap.login(user, password)
        imap.select("INBOX")
        _, data = imap.search(None, f"SINCE {since_date}")
        ids = data[0].split()
        for uid in ids:
            _, msg_data = imap.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            emails.append({
                "uid":        uid,
                "message_id": msg.get("Message-ID", "").strip(),
                "subject":    decode_str(msg.get("Subject", "")),
                "from":       decode_str(msg.get("From", "")),
                "date":       msg.get("Date", ""),
                "body":       extract_imap_body(msg),
                "source":     "imap",
                "boite":      boite,
            })
    return emails


def fetch_imap_emails(days: int = DAYS_BACK) -> list:
    emails = []
    for account in IMAP_ACCOUNTS:
        if not account["password"]:
            print(f"  IMAP {account['user']} : mot de passe manquant, ignoré")
            continue
        try:
            batch = _fetch_imap_account(account["host"], account["user"], account["password"], account["boite"], days)
            print(f"  IMAP {account['user']} : {len(batch)} email(s)")
            emails.extend(batch)
        except Exception as e:
            print(f"  IMAP {account['user']} erreur : {e}")
    return emails


# Gmail API

def get_gmail_service():
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, GMAIL_SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GMAIL_TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _extract_gmail_part(payload: dict) -> tuple:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data", "")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore"), None
    if mime == "text/html" and data:
        return None, base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    plain = html = None
    for part in payload.get("parts", []):
        p, h = _extract_gmail_part(part)
        if p and not plain:
            plain = p
        if h and not html:
            html = h
    return plain, html


def extract_gmail_body(payload: dict) -> str:
    plain, html = _extract_gmail_part(payload)
    if plain:
        return plain
    if html:
        return _html_to_text(html)
    return ""


def _list_gmail_ids(service, query: str, days: int) -> list:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    ids, token = [], None
    while True:
        kwargs = {"userId": "me", "q": f"after:{since} in:inbox {query}", "maxResults": 500}
        if token:
            kwargs["pageToken"] = token
        result = service.users().messages().list(**kwargs).execute()
        ids.extend(m["id"] for m in result.get("messages", []))
        token = result.get("nextPageToken")
        if not token:
            break
    return ids


def _batch_metadata(service, msg_ids: list, batch_size: int = 100) -> dict:
    result = {}

    def _cb(request_id, response, exception):
        if response:
            result[request_id] = response

    for i in range(0, len(msg_ids), batch_size):
        batch = service.new_batch_http_request(callback=_cb)
        for msg_id in msg_ids[i:i + batch_size]:
            batch.add(
                service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ),
                request_id=msg_id,
            )
        batch.execute()

    return result


def fetch_gmail_emails(days: int = DAYS_BACK) -> list:
    service = get_gmail_service()

    cal_q   = '(subject:"annulé :" OR subject:"nouvel événement:" OR subject:"mise à jour:")'
    cal_ids = _list_gmail_ids(service, cal_q, days)

    other_ids = _list_gmail_ids(service, f"-({cal_q})", days)
    print(f"  Gmail : {len(cal_ids)} Calendly + {len(other_ids)} autres")

    metadata      = _batch_metadata(service, other_ids)
    candidate_ids = []
    for msg_id, meta in metadata.items():
        headers = {h["name"]: h["value"] for h in meta["payload"]["headers"]}
        subject = headers.get("Subject", "")
        sender  = headers.get("From", "")
        if not (_SKIP_SUBJECT.search(subject) or _SKIP_SENDER.search(sender)):
            candidate_ids.append(msg_id)
    print(f"  Candidats après filtre : {len(candidate_ids)}/{len(other_ids)}")

    emails = []

    for msg_id in cal_ids:
        full    = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        emails.append({
            "uid":        msg_id,
            "message_id": f"gmail:{msg_id}",
            "subject":    headers.get("Subject", ""),
            "from":       headers.get("From", ""),
            "date":       headers.get("Date", ""),
            "body":       extract_gmail_body(full["payload"]),
            "source":     "gmail",
            "boite":      "bour.chloe0@gmail.com",
        })

    for msg_id in candidate_ids:
        full    = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in metadata[msg_id]["payload"]["headers"]}
        emails.append({
            "uid":        msg_id,
            "message_id": f"gmail:{msg_id}",
            "subject":    headers.get("Subject", ""),
            "from":       headers.get("From", ""),
            "date":       headers.get("Date", ""),
            "body":       extract_gmail_body(full["payload"]),
            "source":     "gmail",
            "boite":      "bour.chloe0@gmail.com",
        })

    return emails


# Helpers

def is_calendly(em: dict) -> bool:
    subject = " ".join(em["subject"].lower().split())
    return any(subject.startswith(p) for p in CALENDLY_PREFIXES)


def extract_name_from_subject(subject: str) -> str:
    m = re.search(r'\bavec\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]+?)(?:\s+le\s+\d|$)', subject.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'(?:nouvel\s+événement|mise\s+à\s+jour)\s*:\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]+?)\s*-\s*\d', subject, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def parse_date_header(date_str: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def extract_guest_email_from_body(body: str) -> str:
    m = re.search(r"Email de l'invité\s*:\s*([\w.+\-]+@[\w.\-]+\.\w+)", body, re.IGNORECASE)
    return m.group(1).strip().lower() if m else ""


def extract_email_from_header(from_str: str) -> str:
    m = re.search(r'<([^>]+@[^>]+)>', from_str)
    if m:
        return m.group(1).strip().lower()
    m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w+', from_str)
    return m.group(0).lower() if m else ""


# Claude

def call_claude(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw   = response.content[0].text.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Pas de JSON : {raw[:200]}")
    return json.loads(raw[start:end])


_SUBJECT_KEYWORDS = [
    "cours de chant", "cours chant", "chorale", "coaching vocal", "whisper",
    "scene ouverte", "scène ouverte", "atelier chant", "inscription", "rattrapage",
    "annulation cours", "absence cours", "tarif", "horaire cours",
]

def classify_email(em: dict) -> dict:
    body = em["body"].strip()
    subject_lower = em["subject"].lower()
    if not body and any(kw in subject_lower for kw in _SUBJECT_KEYWORDS):
        body = "(corps vide — le sujet indique clairement un lien avec les cours de chant)"
    elif not body:
        body = "(corps vide)"
    return call_claude(CLASSIFIER_PROMPT.format(subject=em["subject"], body=body[:3000]))


def parse_calendly_email(em: dict) -> dict:
    body   = em["body"].strip() or "(corps vide)"
    result = call_claude(CALENDLY_PROMPT.format(subject=em["subject"], body=body[:3000]))
    if not result.get("nom_eleve"):
        result["nom_eleve"] = extract_name_from_subject(em["subject"])
    return result


# Notion

def load_all_events_bulk(notion: NotionClient) -> dict:
    """Charge tous les événements dans {email_addr: [pages]}."""
    events, cursor = {}, None
    while True:
        r = notion.databases.query(
            database_id=NOTION_EVENTS_DB,
            **{"start_cursor": cursor} if cursor else {},
        )
        for page in r.get("results", []):
            email_parts = page["properties"].get("Email", {}).get("title", [])
            addr = email_parts[0]["plain_text"].strip().lower() if email_parts else ""
            if addr:
                events.setdefault(addr, []).append(page)
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
    total = sum(len(v) for v in events.values())
    print(f"  {total} événements chargés ({len(events)} emails uniques)")
    return events


def cleanup_event_duplicates(notion: NotionClient, events_cache: dict) -> None:
    """Archive les doublons : garde le premier événement par client."""
    archived = 0
    for pages in events_cache.values():
        for dup in pages[1:]:
            _notion_call(notion.pages.update, page_id=dup["id"], archived=True)
            archived += 1
    if archived:
        print(f"  {archived} doublon(s) archivé(s)")
    for cid in events_cache:
        events_cache[cid] = events_cache[cid][:1]


def _notion_call(fn, *args, retries: int = 3, **kwargs):
    """Exécute un appel Notion avec retries sur timeout."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except NotionTimeout:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  Notion timeout, retry {attempt + 1}/{retries - 1} dans {wait}s...")
            time.sleep(wait)


def _format_resume_entry(date_mail: str, resume: str) -> str:
    if date_mail:
        try:
            dt         = datetime.strptime(date_mail, "%Y-%m-%d")
            date_label = f"{dt.day} {MOIS_FR[dt.month - 1]} {dt.year}"
        except ValueError:
            date_label = date_mail
        return f"{date_label} — {resume}"
    return resume


def upsert_event(notion: NotionClient, events_cache: dict,
                 titre: str, email_addr: str, date_mail: str,
                 info_calendly: str, resume: str, boite: str = "") -> tuple[str, bool]:
    """Met à jour l'événement existant (clé = email_addr), ou en crée un. Retourne (page_id, created)."""
    if info_calendly:
        resume = ""  # les emails Calendly ne touchent jamais "Résumé du mail"
    props: dict = {"Email": {"title": [{"text": {"content": (email_addr or titre)[:200]}}]}}
    try:
        __import__("datetime").date.fromisoformat(date_mail[:10]) if date_mail else None
        _date_ok = bool(date_mail)
    except (ValueError, TypeError):
        _date_ok = False
    if _date_ok:
        props["Date du mail"] = {"date": {"start": date_mail}}
    if info_calendly:
        props["Infos Calendly"] = {"rich_text": [{"text": {"content": info_calendly[:2000]}}]}
    if boite:
        props["Boîte mail"] = {"select": {"name": boite}}

    key = email_addr.lower().strip() if email_addr else ""
    existing_pages = events_cache.get(key, [])

    if resume:
        new_entry = _format_resume_entry(date_mail, resume)
        if existing_pages:
            rt_parts      = existing_pages[0].get("properties", {}).get("Résumé du mail", {}).get("rich_text", [])
            existing_text = rt_parts[0]["plain_text"] if rt_parts else ""
            combined      = f"{new_entry}\n\n{existing_text}".strip() if existing_text else new_entry
        else:
            combined = new_entry
        props["Résumé du mail"] = {"rich_text": [{"text": {"content": combined[:2000]}}]}

    if existing_pages:
        _notion_call(notion.pages.update, page_id=existing_pages[0]["id"], properties=props)
        return existing_pages[0]["id"], False
    else:
        page = _notion_call(notion.pages.create, parent={"database_id": NOTION_EVENTS_DB}, properties=props)
        if key:
            events_cache[key] = [page]
        return page["id"], True


# Processing

def process_email(notion: NotionClient, em: dict, events_cache: dict, processed_ids: set) -> None:
    email_key = get_email_key(em)
    if email_key in processed_ids:
        print("  -> Deja traite, ignore")
        return

    sender_email = extract_email_from_header(em["from"])
    date_mail    = parse_date_header(em["date"])

    if is_calendly(em):
        data        = parse_calendly_email(em)
        email_eleve = extract_guest_email_from_body(em["body"]) or sender_email
        nom_eleve   = data.get("nom_eleve", "")
        type_evt    = data.get("type_evenement", "")
        date_cours  = data.get("date_cours") or ""
        heure_cours = data.get("heure_cours") or ""
        date_mail   = data.get("date_mail") or date_mail

        date_label    = format_date_fr(date_cours, heure_cours) if date_cours else ""
        info_calendly = " - ".join(p for p in ["Calendly", type_evt.capitalize(), date_label] if p)
        titre = nom_eleve.strip() if nom_eleve else (email_eleve.split("@")[0] if email_eleve else "Sans nom")

        _, created = upsert_event(notion, events_cache, titre,
                                  email_eleve, date_mail, info_calendly, "", em.get("boite", ""))
        save_processed_id(email_key, processed_ids)
        action = "Cree" if created else "Mis a jour"
        print(f"  OK {action} : {titre}")

    else:
        result = classify_email(em)
        save_processed_id(email_key, processed_ids)
        if not result.get("is_client"):
            print("  -> Ignore")
            return

        prenom    = result.get("prenom", "")
        nom       = result.get("nom", "")
        resume    = result.get("resume_message", "")
        date_mail = result.get("date_mail") or date_mail

        titre = f"{prenom} {nom}".strip() or sender_email.split("@")[0] or "Sans nom"

        _, created = upsert_event(notion, events_cache, titre,
                                  sender_email, date_mail, "", resume, em.get("boite", ""))
        action = "Cree" if created else "Mis a jour"
        print(f"  OK {action} : {titre}")


# Main

def main():
    notion = NotionClient(auth=NOTION_API_KEY)

    print("Chargement des donnees Notion...")
    events_cache = load_all_events_bulk(notion)
    cleanup_event_duplicates(notion, events_cache)

    print("Chargement des emails deja traites...")
    processed_ids = load_processed_ids()
    print(f"  {len(processed_ids)} email(s) en cache.")

    print(f"Connexion IMAP (fenetre : {DAYS_BACK} jours)...")
    imap_emails = fetch_imap_emails()
    print(f"{len(imap_emails)} email(s) IMAP.\n")

    print("Connexion Gmail (bour.chloe0@gmail.com)...")
    try:
        gmail_emails = fetch_gmail_emails()
        print(f"{len(gmail_emails)} email(s) Gmail retenus.\n")
    except Exception as e:
        print(f"Gmail indisponible : {e}\n")
        gmail_emails = []

    all_emails = imap_emails + gmail_emails
    print(f"Total : {len(all_emails)} email(s) a analyser.\n")

    for em in all_emails:
        print(f"[{em['source'].upper()}] {em['subject'][:60]}")
        try:
            process_email(notion, em, events_cache, processed_ids)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Erreur : {e}")

    print("\nTermine.")


if __name__ == "__main__":
    main()
