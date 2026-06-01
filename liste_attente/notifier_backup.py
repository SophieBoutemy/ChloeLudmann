import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/automations/.env"))

SMTP_HOST    = "smtp.gmail.com"
SMTP_PORT    = 587
SMTP_USER    = "automatisationschloe@gmail.com"
SMTP_PASS    = os.environ.get("GMAIL_AUTOMATION_PASSWORD", "")
MAIL_FROM    = "Chloé Ludmann <automatisationschloe@gmail.com>"
CALENDLY_URL = os.environ.get("CALENDLY_URL", "")

ADMIN_EMAIL   = "contact@chloeludmann.fr"
OVH_SMTP_HOST = "ssl0.ovh.net"
OVH_SMTP_PORT = 465
OVH_SMTP_USER = "contact@chloeludmann.fr"
OVH_SMTP_PASS = os.environ.get("IMAP_PASSWORD", "")


def _send(to_email: str, subject: str, html: str) -> None:
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MAIL_FROM
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_USER, [to_email], msg.as_string())


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


def _html_notification(name: str, event_name: str, start_time: str, end_time: str = "") -> str:
    prenom   = name.split()[0] if name else ""
    greeting = f"Bonjour {prenom} !" if prenom else "Bonjour !"
    slot_text = _fmt_slot(start_time, end_time)
    slot_block = ""
    if slot_text:
        slot_block = (
            f'<p style="margin:0 0 32px 0;font-size:17px;font-weight:700;color:#EA4F26">'
            f'{slot_text}</p>'
        )
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
      <a href="{CALENDLY_URL}"
         style="display:inline-block;background:#EA4F26;color:#ffffff;font-size:15px;
                font-weight:700;text-decoration:none;padding:14px 36px;border-radius:6px;
                letter-spacing:0.3px">
        Réserver ce créneau
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
    subject = f"Nouvelle inscription liste d\u2019attente \u2014 {name}"
    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;color:#222;padding:24px">
  <h2 style="color:#419958">Nouvelle inscription liste d&rsquo;attente</h2>
  <table style="border-collapse:collapse;font-size:15px">
    <tr><td style="padding:6px 16px 6px 0;color:#666">Nom complet</td><td><strong>{name}</strong></td></tr>
    <tr><td style="padding:6px 16px 6px 0;color:#666">Email</td><td><a href="mailto:{email}">{email}</a></td></tr>
    <tr><td style="padding:6px 16px 6px 0;color:#666">Total liste</td><td><strong>{total} personne(s)</strong></td></tr>
  </table>
</body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Automations Chloe <{OVH_SMTP_USER}>"
    msg["To"]      = ADMIN_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    import smtplib as _smtplib
    with _smtplib.SMTP_SSL(OVH_SMTP_HOST, OVH_SMTP_PORT) as smtp:
        smtp.login(OVH_SMTP_USER, OVH_SMTP_PASS)
        smtp.sendmail(OVH_SMTP_USER, [ADMIN_EMAIL], msg.as_string())
    print(f"[notifier] Admin notifie : {name} <{email}> (total={total})")


def notify_all(waitlist: list, event_name: str = "", start_time: str = "", end_time: str = "") -> None:
    for entry in waitlist:
        email = entry.get("email", "")
        name  = entry.get("name", "")
        if not email:
            continue
        html = _html_notification(name, event_name, start_time, end_time)
        _send(email, "🎵 Un créneau vient de se libérer", html)
        print(f"[notifier] Notification envoyée à {name} <{email}>")
