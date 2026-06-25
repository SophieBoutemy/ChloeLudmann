import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote as _urlencode
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

SMTP_HOST    = "in-v3.mailjet.com"
SMTP_PORT    = 587
SMTP_USER    = os.environ.get("MAILJET_API_KEY", "")
SMTP_PASS    = os.environ.get("MAILJET_SECRET_KEY", "")
MAIL_FROM    = "Chloé Ludmann <no-reply@chloeludmann.fr>"
CALENDLY_URL = os.environ.get("CALENDLY_URL", "")

ADMIN_EMAIL   = "contact@chloeludmann.fr"
OVH_SMTP_HOST = "ssl0.ovh.net"
OVH_SMTP_PORT = 465
OVH_SMTP_USER = "contact@chloeludmann.fr"
OVH_SMTP_PASS = os.environ.get("IMAP_PASSWORD", "")


def _send(to_email: str, subject: str, html: str) -> None:
    import base64 as _b64, urllib.request as _ur, json as _js
    message = {
        "From":     {"Email": "no-reply@chloeludmann.fr", "Name": "Chloé Ludmann"},
        "To":       [{"Email": to_email}],
        "Subject":  subject,
        "HTMLPart": html,
    }
    payload     = _js.dumps({"Messages": [message]}).encode()
    credentials = _b64.b64encode(f"{SMTP_USER}:{SMTP_PASS}".encode()).decode()
    req = _ur.Request(
        "https://api.mailjet.com/v3.1/send",
        data=payload,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
        method="POST",
    )
    resp   = _ur.urlopen(req, timeout=15)
    result = _js.loads(resp.read())
    status = result.get("Messages", [{}])[0].get("Status", "unknown")
    if status != "success":
        raise RuntimeError(f"Mailjet status inattendu: {result}")


_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS  = ["janvier", "février", "mars", "avril", "mai", "juin",
          "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
_PARIS = timezone(timedelta(hours=2))  # CEST (heure d'été)


def _parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(_PARIS)


def _fmt_slot(start_time: str, end_time: str) -> str:
    if not start_time:
        return ""
    try:
        dt_start = _parse_iso(start_time)
        jour  = _JOURS[dt_start.weekday()]
        date  = f"{dt_start.day} {_MOIS[dt_start.month - 1]}"
        h_deb = dt_start.strftime("%Hh%M").replace("h00", "h")
        if end_time:
            dt_end = _parse_iso(end_time)
            h_fin  = dt_end.strftime("%Hh%M").replace("h00", "h")
            return f"{jour} {date} de {h_deb} à {h_fin}"
        return f"{jour} {date} à {h_deb}"
    except Exception:
        return start_time


def _html_notification(name: str, event_name: str, start_time: str, end_time: str = "", booking_url: str = "", email: str = "") -> str:
    prenom   = name.split()[0] if name else ""
    greeting = f"Bonjour {prenom} !" if prenom else "Bonjour !"
    slot_text = _fmt_slot(start_time, end_time)
    slot_block = ""
    if slot_text:
        slot_block = (
            f'<p style="margin:0 0 32px 0;font-size:17px;font-weight:700;color:#EA4F26">'
            f'{slot_text}</p>'
        )
    unsubscribe_url = f"https://automations.chloeludmann.fr/unsubscribe?email={_urlencode(email)}"
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background-color:#F8EFE2;font-family:'Roboto',Arial,sans-serif">
  <div style="max-width:580px;margin:32px auto;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.10)">

    <!-- Header -->
    <div style="background:#419958;padding:28px 32px">
      <p style="margin:0;color:#ffffff;font-size:18px;font-weight:700;letter-spacing:0.3px">
        Chloé Ludmann — Cours de chant
      </p>
    </div>

    <!-- Body -->
    <div style="background:#ffffff;padding:36px 32px">
      <p style="margin:0 0 24px 0;font-size:16px;color:#222;font-weight:500">{greeting}</p>
      <p style="margin:0 0 20px 0;font-size:15px;color:#333">Un créneau vient de se libérer :</p>
      {slot_block}
      <a href="{booking_url or CALENDLY_URL}"
         style="display:inline-block;background:#EA4F26;color:#ffffff;font-size:15px;
                font-weight:700;text-decoration:none;padding:14px 36px;border-radius:6px;
                letter-spacing:0.3px">
        Réserver ce créneau
      </a>
    </div>

    <!-- Unsubscribe -->
    <div style="background:#ffffff;padding:0 32px 28px 32px;text-align:center">
      <a href="{unsubscribe_url}"
         style="font-size:12px;color:#aaa;text-decoration:underline">
        Se désinscrire de la liste d'attente
      </a>
    </div>

    <!-- Footer -->
    <div style="background:#419958;padding:16px 32px;text-align:center">
      <p style="margin:0;color:#ffffff;font-size:13px;opacity:0.92">
        Professeure de chant à Rennes —
        <a href="mailto:contact@chloeludmann.fr"
           style="color:#ffffff;text-decoration:underline">contact@chloeludmann.fr</a>
      </p>
    </div>

  </div>
</body>
</html>"""


def _html_confirmation(name: str) -> str:
    prenom = name.split()[0] if name else ""
    greeting = f"Bonjour {prenom}," if prenom else "Bonjour,"
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background-color:#F8EFE2;font-family:'Roboto',Arial,sans-serif">
  <div style="max-width:580px;margin:32px auto;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.10)">

    <!-- Header -->
    <div style="background:#419958;padding:28px 32px">
      <p style="margin:0;color:#ffffff;font-size:18px;font-weight:700;letter-spacing:0.3px">
        Chloé Ludmann — Cours de chant
      </p>
    </div>

    <!-- Body -->
    <div style="background:#ffffff;padding:36px 32px">
      <p style="margin:0 0 20px 0;font-size:16px;color:#222;font-weight:500">{greeting}</p>
      <p style="margin:0 0 16px 0;font-size:15px;color:#333;line-height:1.7">
        Votre inscription sur la liste d'attente est bien confirmée.
      </p>
      <p style="margin:0 0 32px 0;font-size:15px;color:#333;line-height:1.7">
        Vous recevrez un email dès qu'un créneau se libère.
      </p>
      <p style="margin:0 0 4px 0;font-size:15px;color:#333">À bientôt,</p>
      <p style="margin:0;font-size:16px;font-weight:700;color:#EA4F26">Chloé Ludmann</p>
    </div>

    <!-- Footer -->
    <div style="background:#419958;padding:16px 32px;text-align:center">
      <p style="margin:0;color:#ffffff;font-size:13px;opacity:0.92">
        Professeure de chant à Rennes —
        <a href="mailto:contact@chloeludmann.fr"
           style="color:#ffffff;text-decoration:underline">contact@chloeludmann.fr</a>
      </p>
    </div>

  </div>
</body>
</html>"""


def send_confirmation_email(name: str, email: str) -> None:
    html = _html_confirmation(name)
    _send(email, "Inscription confirmée – Liste d'attente", html)
    print(f"[notifier] Confirmation envoyée à {name} <{email}>")


def send_admin_notification(name: str, email: str, total: int) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Nouvelle inscription liste d'attente — {name}"
    msg['From'] = f'Chloe Ludmann <{SMTP_USER}>'
    msg['To'] = ADMIN_EMAIL
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Roboto&display=swap" rel="stylesheet">
</head><body style="margin:0;padding:0;background:#F8EFE2;font-family:Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:30px 0;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#F8EFE2;">
<tr><td style="background:#419958;padding:24px 32px;border-radius:8px 8px 0 0;">
<span style="color:#ffffff;font-size:20px;font-weight:bold;">Nouvelle inscription — liste d'attente</span>
</td></tr>
<tr><td style="padding:32px;background:#ffffff;">
<p style="margin:0 0 12px;font-size:16px;"><b>Nom :</b> {name}</p>
<p style="margin:0 0 12px;font-size:16px;"><b>Email :</b> <a href="mailto:{email}" style="color:#EA4F26;">{email}</a></p>
<p style="margin:0;font-size:16px;"><b>Total sur la liste :</b> {total} personne(s)</p>
</td></tr>
<tr><td style="background:#419958;padding:16px 32px;border-radius:0 0 8px 8px;text-align:center;">
<span style="color:#ffffff;font-size:13px;">contact@chloeludmann.fr</span>
</td></tr>
</table></td></tr></table>
</body></html>"""
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, ADMIN_EMAIL, msg.as_string())
    print(f'[notifier] Admin notifie : {name} <{email}> (total={total})')

def notify_all(waitlist: list, event_name: str = "", start_time: str = "", end_time: str = "", booking_url: str = "") -> None:
    for entry in waitlist:
        email = entry.get("email", "")
        name  = entry.get("name", "")
        if not email:
            continue
        html = _html_notification(name, event_name, start_time, end_time, booking_url, email)
        try:
            _send(email, "🎵 Un créneau vient de se libérer", html)
            print(f"[notifier] Notification envoyée à {name} <{email}>")
        except Exception as e:
            print(f"[notifier] Erreur envoi à {name} <{email}> : {e}")
