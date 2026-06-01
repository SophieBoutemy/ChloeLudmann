import subprocess
from flask import Flask

app = Flask(__name__)

PYTHON  = '/home/ubuntu/automations/venv/bin/python'
SCRIPT  = '/home/ubuntu/automations/factures/factures.py'
WORKDIR = '/home/ubuntu/automations'

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Scan factures</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: rgba(0, 0, 0, 0.55);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .popup {{
      background: #fff;
      border-radius: 14px;
      padding: 48px 56px 40px;
      max-width: 480px;
      width: 90%;
      text-align: center;
      box-shadow: 0 8px 32px rgba(0,0,0,0.18);
    }}
    .popup p {{
      font-family: Georgia, serif;
      font-size: 1.2rem;
      color: #1a1a1a;
      line-height: 1.6;
      margin-bottom: 32px;
    }}
    .popup button {{
      background: #419958;
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 12px 36px;
      font-size: 1rem;
      font-family: Georgia, serif;
      cursor: pointer;
    }}
    .popup button:hover {{
      background: #357a45;
    }}
  </style>
</head>
<body>
  <div class="popup">
    <p>{message}</p>
    <button onclick="window.close()">Fermer</button>
  </div>
</body>
</html>"""


@app.route('/scan-factures')
def scan_factures():
    result = subprocess.run([PYTHON, SCRIPT], capture_output=True, text=True, cwd=WORKDIR)
    count = result.stdout.count('Notion OK')
    if count > 0:
        message = f'&#10003; Scan termin&#233; &mdash; {count} nouvelle(s) facture(s) ajout&#233;e(s) dans Notion'
    else:
        message = '&#10003; Aucune nouvelle facture d&#233;tect&#233;e'
    return HTML_TEMPLATE.format(message=message), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5004)
