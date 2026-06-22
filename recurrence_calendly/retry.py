#!/usr/bin/env python3
"""
recurrence_calendly/retry.py
Cron quotidien (7h) — tente de réserver les créneaux en attente dans pending.db
au fur et à mesure qu'ils entrent dans la fenêtre des 60 jours Calendly.

Résultats possibles par créneau :
  - Réservé     → supprimé de pending, email de confirmation au client
  - Toujours hors fenêtre → skip (sera réessayé demain)
  - Dans fenêtre mais indisponible → retry_count++ ; abandon + email après 5 échecs
  - Date passée sans réservation → supprimé de pending, email au client
"""

import json
import logging
import os
import smtplib
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

# ── Config ────────────────────────────────────────────────────────────────────

CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
SMTP_USER      = "boutemy.automatisation@gmail.com"
SMTP_PASS      = os.environ["GMAIL_AUTOMATION_PASSWORD"]
CHLOE_EMAIL    = "contact@chloeludmann.fr"

WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "58"))
MAX_RETRIES    = 5    # nb d'échecs consécutifs dans la fenêtre avant abandon

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending.db")
LOG_FILE = os.path.expanduser("~/automations/logs/recurrence_retry.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

CALENDLY_HEADERS = {
    "Authorization": f"Bearer {CALENDLY_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; automations-chloe/1.0)",
}


# ── Helpers Calendly ──────────────────────────────────────────────────────────

def calendly_get(url):
    req  = urllib.request.Request(url, headers=CALENDLY_HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def calendly_post(url, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=CALENDLY_HEADERS, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode(errors="replace"))


def is_slot_available(event_type_uri: str, dt_utc: datetime) -> bool:
    start  = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    end    = (dt_utc + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    target = dt_utc.strftime("%Y-%m-%dT%H:%M")
    url = (
        "https://api.calendly.com/event_type_available_times"
        f"?event_type={urllib.parse.quote(event_type_uri, safe='')}"
        f"&start_time={urllib.parse.quote(start, safe='')}"
        f"&end_time={urllib.parse.quote(end, safe='')}"
    )
    try:
        data = calendly_get(url)
        return any(
            s.get("status") == "available" and s.get("start_time", "").startswith(target)
            for s in data.get("collection", [])
        )
    except Exception as e:
        log.warning(f"Erreur available_times {dt_utc}: {e}")
        return False


def book_slot(event_type_uri: str, location: dict, dt_utc: datetime,
              name: str, email: str) -> tuple[bool, str]:
    payload = {
        "event_type": event_type_uri,
        "start_time": dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "invitee": {"name": name, "email": email, "timezone": "Europe/Paris"},
        "location": location,
    }
    code, resp = calendly_post("https://api.calendly.com/invitees", payload)
    if code in (200, 201):
        return True, resp.get("resource", {}).get("uri", "")
    details = resp.get("details", [])
    codes   = [d.get("code", "") for d in details]
    if "already_filled" in codes:
        return False, "already_filled"
    return False, f"erreur_{code}"


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, html_body):
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [to_addr], msg.as_string())


def _email_confirmation(email_addr, prenom, slots):
    """Email au client quand un ou plusieurs créneaux sont finalement réservés."""
    td  = "padding:6px 14px"
    th  = "text-align:left;padding:6px 14px;background:#f5f5f5;border-bottom:1px solid #ddd"
    tbl = "border-collapse:collapse;width:100%;max-width:560px"
    rows = "".join(
        f"<tr><td style='{td}'>{s['date']} ({s['jour_nom'].capitalize()})</td>"
        f"<td style='{td}'>{s['heure_str']}</td>"
        f"<td style='{td};color:#2a7a2a'>Réservé ✓</td></tr>"
        for s in slots
    )
    type_cours = slots[0]["type_cours"] if slots else ""
    html = f"""
<html><body style="font-family:sans-serif;color:#222;max-width:620px;margin:0 auto;padding:24px">
<p>Bonjour {prenom},</p>
<p>Bonne nouvelle ! Le(s) créneau(x) suivant(s) de <strong>{type_cours}</strong>
   vient d'être réservé automatiquement :</p>
<table style="{tbl}">
  <tr><th style="{th}">Date</th><th style="{th}">Heure</th><th style="{th}">Statut</th></tr>
  {rows}
</table>
<p style="font-size:0.88em;color:#555">
  Vous recevrez une confirmation Calendly avec l'invitation dans votre calendrier
  et les rappels habituels.
</p>
<hr style="margin-top:32px;border:none;border-top:1px solid #eee">
<p style="font-size:0.85em;color:#888">
  Cours avec Chloé Ludmann — 6 rue Desaix, 35000 Rennes<br>
  <a href="https://chloeludmann.fr">chloeludmann.fr</a>
</p>
</body></html>"""
    n = len(slots)
    send_email(email_addr,
               f"Votre cours de chant — {'créneau confirmé' if n == 1 else str(n) + ' créneaux confirmés'} !",
               html)


def _email_indisponible(email_addr, prenom, slots):
    """Email au client quand un créneau est définitivement indisponible."""
    td  = "padding:6px 14px"
    th  = "text-align:left;padding:6px 14px;background:#f5f5f5;border-bottom:1px solid #ddd"
    tbl = "border-collapse:collapse;width:100%;max-width:560px"
    rows = "".join(
        f"<tr><td style='{td};color:#cc0000'>{s['date']} ({s['jour_nom'].capitalize()})</td>"
        f"<td style='{td};color:#cc0000'>{s['heure_str']}</td>"
        f"<td style='{td};color:#cc0000'>Indisponible</td></tr>"
        for s in slots
    )
    type_cours = slots[0]["type_cours"] if slots else ""
    html = f"""
<html><body style="font-family:sans-serif;color:#222;max-width:620px;margin:0 auto;padding:24px">
<p>Bonjour {prenom},</p>
<p>Malheureusement, le(s) créneau(x) suivant(s) de <strong>{type_cours}</strong>
   n'ont pas pu être réservés :</p>
<table style="{tbl}">
  <tr><th style="{th}">Date</th><th style="{th}">Heure</th><th style="{th}">Statut</th></tr>
  {rows}
</table>
<p style="color:#555">
  Ces créneaux sont soit déjà pris, soit en dehors des disponibilités de Chloé.
  N'hésitez pas à la contacter directement pour trouver une alternative.
</p>
<hr style="margin-top:32px;border:none;border-top:1px solid #eee">
<p style="font-size:0.85em;color:#888">
  Cours avec Chloé Ludmann — 6 rue Desaix, 35000 Rennes<br>
  <a href="https://chloeludmann.fr">chloeludmann.fr</a>
</p>
</body></html>"""
    send_email(email_addr, "Votre cours de chant — créneau(x) indisponible(s)", html)


def _notify_chloe(email_addr, prenom, nom, booked_slots, unavailable_slots):
    """Notifie Chloé des réservations automatiques réussies ou abandonnées."""
    if not booked_slots and not unavailable_slots:
        return
    td = "padding:4px 12px"
    th = "text-align:left;padding:4px 12px"
    rows_ok = "".join(
        f"<tr><td style='{td}'>{s['date']} ({s['jour_nom'].capitalize()})</td>"
        f"<td style='{td}'>{s['heure_str']}</td>"
        f"<td style='{td};color:#2a7a2a'>Réservé ✓</td></tr>"
        for s in booked_slots
    )
    rows_ko = "".join(
        f"<tr><td style='{td}'>{s['date']} ({s['jour_nom'].capitalize()})</td>"
        f"<td style='{td}'>{s['heure_str']}</td>"
        f"<td style='{td};color:#cc0000'>Indisponible</td></tr>"
        for s in unavailable_slots
    )
    type_cours = (booked_slots or unavailable_slots)[0]["type_cours"]
    html = f"""
<html><body style="font-family:sans-serif;color:#222;padding:16px">
<h3>Réservation automatique — {nom}</h3>
<p>{nom}, {email_addr} — {type_cours}</p>
<table style="border-collapse:collapse">
  <tr><th style="{th}">Date</th><th style="{th}">Heure</th><th style="{th}">Statut</th></tr>
  {rows_ok}{rows_ko}
</table>
</body></html>"""

    n_ok = len(booked_slots)
    n_ko = len(unavailable_slots)
    subject = f"[Récurrence auto] {nom} — {n_ok} réservé(s)" + (f" / {n_ko} indisponible(s)" if n_ko else "")
    send_email(CHLOE_EMAIL, subject, html)


# ── Boucle principale ─────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM pending ORDER BY dt_utc ASC").fetchall()
    log.info(f"Relance quotidienne : {len(rows)} créneau(x) en attente")

    today        = date.today()
    window_limit = today + timedelta(days=WINDOW_DAYS)

    # Regroupement des résultats par client pour envoi d'emails groupés
    # Structure : { email: { "prenom": ..., "nom": ..., "booked": [...], "unavailable": [...] } }
    by_client: dict = {}

    def _get_client(email_addr, prenom, nom):
        if email_addr not in by_client:
            by_client[email_addr] = {"prenom": prenom, "nom": nom, "booked": [], "unavailable": []}
        return by_client[email_addr]

    for row in rows:
        dt_utc  = datetime.fromisoformat(row["dt_utc"])
        d_local = dt_utc.date()
        slot    = {
            "date":      dt_utc.strftime("%d/%m/%Y"),
            "heure_str": row["heure_str"],
            "type_cours": row["type_cours"],
            "jour_nom":  row["jour_nom"],
        }

        # Date passée sans réservation → abandon
        if d_local < today:
            log.info(f"Date passée sans réservation : {row['dt_utc']} — suppression")
            conn.execute("DELETE FROM pending WHERE id = ?", (row["id"],))
            _get_client(row["email"], row["prenom_affiche"], row["nom"])["unavailable"].append(slot)
            continue

        # Toujours hors fenêtre → skip
        if d_local > window_limit:
            log.info(f"Hors fenêtre ({d_local} > {window_limit}) : skip")
            continue

        # Dans la fenêtre — vérification de dispo
        location = json.loads(row["location_json"])

        if not is_slot_available(row["event_type_uri"], dt_utc):
            new_count = row["retry_count"] + 1
            conn.execute(
                "UPDATE pending SET retry_count = ?, last_retry = ? WHERE id = ?",
                (new_count, today.isoformat(), row["id"]),
            )
            log.info(f"Indisponible dans la fenêtre (tentative {new_count}/{MAX_RETRIES}) : {row['dt_utc']}")

            if new_count >= MAX_RETRIES:
                log.warning(f"Abandon après {new_count} tentatives : {row['dt_utc']}")
                conn.execute("DELETE FROM pending WHERE id = ?", (row["id"],))
                _get_client(row["email"], row["prenom_affiche"], row["nom"])["unavailable"].append(slot)
            continue

        # Créneau dispo — on réserve
        ok, detail = book_slot(row["event_type_uri"], location, dt_utc, row["nom"], row["email"])

        if ok:
            log.info(f"Réservé avec succès : {row['dt_utc']} pour {row['email']}")
            conn.execute("DELETE FROM pending WHERE id = ?", (row["id"],))
            _get_client(row["email"], row["prenom_affiche"], row["nom"])["booked"].append(slot)

        elif detail == "already_filled":
            log.info(f"Créneau déjà pris : {row['dt_utc']}")
            conn.execute("DELETE FROM pending WHERE id = ?", (row["id"],))
            _get_client(row["email"], row["prenom_affiche"], row["nom"])["unavailable"].append(slot)

        else:
            # Erreur inattendue — on incrémente et on laisse
            new_count = row["retry_count"] + 1
            conn.execute(
                "UPDATE pending SET retry_count = ?, last_retry = ? WHERE id = ?",
                (new_count, today.isoformat(), row["id"]),
            )
            log.warning(f"Erreur booking (tentative {new_count}) : {row['dt_utc']} — {detail}")

    conn.commit()
    conn.close()

    # Envoi des emails groupés par client
    for email_addr, info in by_client.items():
        prenom = info["prenom"]
        nom    = info["nom"]

        if info["booked"]:
            try:
                _email_confirmation(email_addr, prenom, info["booked"])
                log.info(f"Email confirmation envoyé à {email_addr} ({len(info['booked'])} créneau(x))")
            except Exception as e:
                log.error(f"Erreur email confirmation {email_addr}: {e}")

        if info["unavailable"]:
            try:
                _email_indisponible(email_addr, prenom, info["unavailable"])
                log.info(f"Email indisponible envoyé à {email_addr} ({len(info['unavailable'])} créneau(x))")
            except Exception as e:
                log.error(f"Erreur email indisponible {email_addr}: {e}")

        if info["booked"] or info["unavailable"]:
            try:
                _notify_chloe(email_addr, prenom, nom, info["booked"], info["unavailable"])
                log.info(f"Notif Chloé envoyée pour {email_addr}")
            except Exception as e:
                log.error(f"Erreur notif Chloé pour {email_addr}: {e}")

if __name__ == "__main__":
    main()
