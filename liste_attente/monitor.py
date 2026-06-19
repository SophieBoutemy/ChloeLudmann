#!/usr/bin/env python3
"""
Surveillance quotidienne du service liste-attente.
- Verifie le webhook Calendly (actif ?)
- Verifie le SMTP (envoi test a soi-meme)
- Alerte contact@sophieboutemy.com si l'un des deux echoue
"""
import os, sys, json, smtplib, urllib.request, urllib.error
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

CALENDLY_TOKEN     = os.environ.get("CALENDLY_TOKEN", "")
CALENDLY_WEBHOOK_ID = "f4b53d6c-ca7c-4632-8eee-1f94879148a4"
SMTP_HOST          = "smtp.gmail.com"
SMTP_PORT          = 587
SMTP_USER          = "boutemy.automatisation@gmail.com"
SMTP_PASS          = os.environ.get("GMAIL_AUTOMATION_PASSWORD", "")
ALERT_TO           = "contact@sophieboutemy.com"
LOG_FILE           = os.path.expanduser("~/automations/logs/monitor.log")

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
errors = []


def log(msg):
    line = f"[{now}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── 1. Webhook Calendly ──────────────────────────────────────────────────────
def check_webhook():
    url = f"https://api.calendly.com/webhook_subscriptions/{CALENDLY_WEBHOOK_ID}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {CALENDLY_TOKEN}",
        "User-Agent": "monitor/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        state = data.get("resource", {}).get("state", "unknown")
        if state == "active":
            log(f"[OK] Webhook Calendly {CALENDLY_WEBHOOK_ID[:8]}... : {state}")
        else:
            msg = f"Webhook Calendly en etat '{state}' (attendu: active)"
            log(f"[FAIL] {msg}")
            errors.append(msg)
    except urllib.error.HTTPError as e:
        msg = f"Webhook Calendly inaccessible : HTTP {e.code}"
        log(f"[FAIL] {msg}")
        errors.append(msg)
    except Exception as e:
        msg = f"Webhook Calendly erreur : {e}"
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
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [SMTP_USER], msg.as_string())
        log(f"[OK] SMTP : mail de test envoye vers {SMTP_USER}")
    except Exception as e:
        err = f"SMTP echec : {e}"
        log(f"[FAIL] {err}")
        errors.append(err)


# ── 3. Alerte si erreurs ─────────────────────────────────────────────────────
def send_alert():
    body_lines = "\n".join(f"- {e}" for e in errors)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;
            padding:32px;box-shadow:0 2px 6px rgba(0,0,0,.1)">
  <h2 style="color:#c0392b;margin:0 0 16px">⚠ Alerte service liste-attente</h2>
  <p style="color:#555;margin:0 0 12px">Date : {now}</p>
  <p style="color:#555;margin:0 0 20px">
    Les verifications automatiques ont detecte {len(errors)} probleme(s) :
  </p>
  <ul style="color:#333;line-height:1.8">
    {"".join(f"<li>{e}</li>" for e in errors)}
  </ul>
  <hr style="margin:24px 0;border:none;border-top:1px solid #eee">
  <p style="color:#888;font-size:13px">
    Serveur : ov-824f0c.infomaniak.ch — Service : liste-attente.service
  </p>
</div>
</body></html>"""

    alert = MIMEMultipart("alternative")
    alert["Subject"] = f"[ALERTE] Liste-attente — {len(errors)} probleme(s)"
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
