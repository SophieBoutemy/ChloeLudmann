#!/usr/bin/env python3
"""Envoie une alerte email via Gmail SMTP. Usage: send_alert.py <subject> <body>"""
import smtplib
import sys
from email.mime.text import MIMEText

ENV_PATH = '/home/ubuntu/automations/.env'
FROM_ADDR = 'boutemy.automatisation@gmail.com'
TO_ADDR = 'contact@sophieboutemy.com'


def load_env_var(path, key):
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith(f'{key}='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ''


def main():
    if len(sys.argv) < 3:
        print('Usage: send_alert.py <subject> <body>', file=sys.stderr)
        sys.exit(1)
    subject, body = sys.argv[1], sys.argv[2]
    smtp_pass = load_env_var(ENV_PATH, 'GMAIL_AUTOMATION_PASSWORD')
    if not smtp_pass:
        print('GMAIL_AUTOMATION_PASSWORD manquant dans .env, alerte non envoyee', file=sys.stderr)
        sys.exit(1)
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = FROM_ADDR
    msg['To'] = TO_ADDR
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(FROM_ADDR, smtp_pass)
        s.send_message(msg)
    print('Alerte envoyee.')


if __name__ == '__main__':
    main()
