import smtplib, os
from email.mime.text import MIMEText
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/automations/.env"))
user = os.getenv("IMAP_EMAIL")
pwd  = os.getenv("SMTP_PASS") or os.getenv("IMAP_PASSWORD")
msg = MIMEText("Test confirmation liste attente")
msg["Subject"] = "Test confirmation"
msg["From"]    = user
msg["To"]      = "contact@sophieboutmy.com"
with smtplib.SMTP_SSL("ssl0.ovh.net", 465) as s:
    s.set_debuglevel(2)
    s.login(user, pwd)
    result = s.sendmail(user, "contact@sophieboutmy.com", msg.as_string())
    print("Résultat:", result)
