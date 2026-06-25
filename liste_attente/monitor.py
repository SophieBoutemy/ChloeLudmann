#!/usr/bin/env python3
"""
Surveillance du service liste-attente (toutes les 4h).
- Verifie le webhook Calendly (actif ?)  → auto-recreation si desactive
- Verifie le SMTP (envoi test a soi-meme)
- Alerte contact@sophieboutemy.com si probleme (meme auto-repare)
"""
import os, sys, json, smtplib, urllib.request, urllib.error
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

CALENDLY_TOKEN       = os.environ.get("CALENDLY_TOKEN", "")
CALENDLY_WEBHOOK_ID  = "4933b368-b8cc-47bd-83ed-36e7d1d8b706"  # mis a jour le 2026-06-25
ORG_URI              = "https://api.calendly.com/organizations/28356bab-3866-4892-8109-7821b03e5154"
WEBHOOK_CALLBACK_URL = "https://automations.chloeludmann.fr/calendly"
WEBHOOK_STATE_FILE   = os.path.expanduser("~/automations/liste_attente/webhook_state.json")

SMTP_HOST  = "smtp.gmail.com"
SMTP_PORT  = 587
SMTP_USER  = "boutemy.automatisation@gmail.com"
SMTP_PASS  = os.environ.get("GMAIL_AUTOMATION_PASSWORD", "")
ALERT_TO   = "contact@sophieboutemy.com"
LOG_FILE   = os.path.expanduser("~/automations/logs/monitor.log")

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
errors = []


def log(msg):
    line = f"[{now}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Gestion UUID webhook (persistance entre recreations) ─────────────────────

def _get_webhook_id():
    try:
        with open(WEBHOOK_STATE_FILE) as f:
            return json.load(f).get("id", CALENDLY_WEBHOOK_ID)
    except Exception:
        return CALENDLY_WEBHOOK_ID


def _save_webhook_id(wid):
    with open(WEBHOOK_STATE_FILE, "w") as f:
        json.dump({"id": wid, "updated": now}, f)


def _recreate_webhook():
    """Supprime le webhook desactive et en cree un nouveau. Retourne le nouvel UUID ou None."""
    current_id = _get_webhook_id()
    hdrs = {
        "Authorization": f"Bearer {CALENDLY_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "monitor/1.0",
    }
    # DELETE (ignore les erreurs 404 si deja supprime)
    try:
        req = urllib.request.Request(
            f"https://api.calendly.com/webhook_subscriptions/{current_id}",
            headers=hdrs, method="DELETE"
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"[RECOVER] DELETE webhook {current_id[:8]}... OK")
    except urllib.error.HTTPError as e:
        log(f"[RECOVER] DELETE webhook {current_id[:8]}... HTTP {e.code} (ignore)")
    except Exception as e:
        log(f"[RECOVER] DELETE webhook {current_id[:8]}... erreur (ignore) : {e}")

    # POST nouveau
    body = json.dumps({
        "url": WEBHOOK_CALLBACK_URL,
        "events": ["invitee.canceled"],
        "organization": ORG_URI,
        "scope": "organization",
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.calendly.com/webhook_subscriptions",
            data=body, headers=hdrs, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        new_id = data["resource"]["uri"].split("/")[-1]
        _save_webhook_id(new_id)
        log(f"[RECOVER] Nouveau webhook cree : {new_id[:8]}... (state={data['resource']['state']})")
        return new_id
    except Exception as e:
        log(f"[FAIL] Recreation webhook echouee : {e}")
        return None


# ── 1. Webhook Calendly ──────────────────────────────────────────────────────

def check_webhook():
    current_id = _get_webhook_id()
    url = f"https://api.calendly.com/webhook_subscriptions/{current_id}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {CALENDLY_TOKEN}",
        "User-Agent": "monitor/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        state = data.get("resource", {}).get("state", "unknown")
        if state == "active":
            log(f"[OK] Webhook Calendly {current_id[:8]}... : {state}")
            return
        # Desactive ou etat inconnu → auto-recovery
        log(f"[FAIL] Webhook {current_id[:8]}... en etat '{state}' — auto-recovery...")
        new_id = _recreate_webhook()
        if new_id:
            errors.append(
                f"Webhook Calendly etait '{state}' → recree automatiquement "
                f"(ancien : {current_id[:8]}..., nouveau : {new_id[:8]}...)"
            )
        else:
            errors.append(f"Webhook Calendly en etat '{state}' ET recreation echouee — intervention manuelle requise")

    except urllib.error.HTTPError as e:
        if e.code == 404:
            log(f"[FAIL] Webhook {current_id[:8]}... introuvable (404) — auto-recovery...")
            new_id = _recreate_webhook()
            if new_id:
                errors.append(
                    f"Webhook Calendly introuvable (supprime ?) → recree automatiquement "
                    f"(nouvel ID : {new_id[:8]}...)"
                )
            else:
                errors.append("Webhook Calendly introuvable (404) ET recreation echouee — intervention manuelle requise")
        else:
            msg = f"Webhook Calendly inaccessible : HTTP {e.code}"
            log(f"[FAIL] {msg}")
            errors.append(msg)
    except Exception as e:
        msg = f"Webhook Calendly erreur reseau : {e}"
        log(f"[FAIL] {msg}")
        errors.append(msg)


# ── 2. SMTP self-test ────────────────────────────────────────────────────────

def check_smtp():
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Monitor OK] Liste attente — {now}"
    msg["From"]    = f"Monitor <{SMTP_USER}>"
    msg["To"]      = SMTP_USER
    msg.attach(MIMEText(
        f"<p>Surveillance automatique — {now}<br>SMTP operationnel.</p>",
        "html", "utf-8"
    ))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [SMTP_USER], msg.as_string())
        log(f"[OK] SMTP : mail de test envoye vers {SMTP_USER}")
    except Exception as e:
        err = f"SMTP echec : {e}"
        log(f"[FAIL] {err}")
        errors.append(err)


# ── 3. Alerte si erreurs ─────────────────────────────────────────────────────

def send_alert():
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;
            padding:32px;box-shadow:0 2px 6px rgba(0,0,0,.1)">
  <h2 style="color:#c0392b;margin:0 0 16px">Alerte service liste-attente</h2>
  <p style="color:#555;margin:0 0 12px">Date : {now}</p>
  <p style="color:#555;margin:0 0 20px">
    Les verifications automatiques ont detecte {len(errors)} probleme(s) :
  </p>
  <ul style="color:#333;line-height:1.8">
    {"".join(f"<li>{e}</li>" for e in errors)}
  </ul>
  <p style="color:#888;font-size:13px;margin-top:8px">
    (Si la ligne indique "recree automatiquement", le service est deja retabli.)
  </p>
  <hr style="margin:24px 0;border:none;border-top:1px solid #eee">
  <p style="color:#888;font-size:13px">
    Serveur : ov-824f0c — Service : liste-attente.service — Monitor toutes les 4h
  </p>
</div>
</body></html>"""

    alert = MIMEMultipart("alternative")
    alert["Subject"] = f"[ALERTE] Liste-attente — {len(errors)} probleme(s) detecte(s)"
    alert["From"]    = f"Monitor <{SMTP_USER}>"
    alert["To"]      = ALERT_TO
    alert.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [ALERT_TO], alert.as_string())
        log(f"[ALERT] Mail d'alerte envoye a {ALERT_TO}")
    except Exception as e:
        log(f"[ALERT-FAIL] Impossible d'envoyer l'alerte : {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

log("=== Surveillance demarree ===")
check_webhook()
check_smtp()

if errors:
    send_alert()
else:
    log("[OK] Tous les checks passes — aucune alerte")

log("=== Surveillance terminee ===")
sys.exit(1 if errors else 0)
