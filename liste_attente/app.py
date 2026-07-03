import json
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import notifier

load_dotenv(os.path.expanduser("~/automations/.env"))

app = Flask(__name__)

WAITLIST_FILE = os.path.join(os.path.dirname(__file__), "waitlist.json")


def load_waitlist():
    with open(WAITLIST_FILE, "r") as f:
        return json.load(f)


def save_waitlist(data):
    with open(WAITLIST_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.route("/tally", methods=["POST"])
def tally_webhook():
    body   = request.get_json(silent=True) or {}
    fields = body.get("data", {}).get("fields", [])

    email = ""
    name  = ""
    for field in fields:
        label = field.get("label", "").lower()
        ftype = field.get("type", "")
        value = field.get("value", "")
        if not value:
            continue
        if ftype == "INPUT_EMAIL" or "email" in label:
            email = str(value).strip().lower()
        elif ftype in ("INPUT_TEXT", "MULTIPLE_CHOICE") and any(
            k in label for k in ("nom", "name", "prénom", "prenom")
        ):
            name = str(value).strip()

    if not email:
        return jsonify({"status": "ignored", "reason": "no email"}), 200

    waitlist = load_waitlist()
    if any(e.get("email") == email for e in waitlist):
        return jsonify({"status": "duplicate"}), 200

    waitlist.append({"name": name, "email": email})
    save_waitlist(waitlist)
    print(f"[tally] Ajout liste d'attente : {name} <{email}>")

    try:
        notifier.send_confirmation_email(name, email)
    except Exception as e:
        print(f"[tally] Erreur confirmation email : {e}")

    try:
        notifier.send_admin_notification(name, email, len(waitlist))
    except Exception as e:
        print(f"[tally] Erreur notif admin : {e}")

    return jsonify({"status": "added"}), 200


@app.route("/calendly", methods=["POST"])
def calendly_webhook():
    body  = request.get_json(silent=True) or {}
    event = body.get("event", "")
    print(f"[calendly] Webhook recu: {body}")

    if event != "invitee.canceled":
        return jsonify({"status": "ignored"}), 200

    try:
        waitlist = load_waitlist()
        if not waitlist:
            return jsonify({"status": "waitlist_empty"}), 200

        payload        = body.get("payload", {})
        event_name     = payload.get("event_type", {}).get("name", "")
        event_uri      = payload.get("event", "")
        event_uuid     = event_uri.rstrip("/").split("/")[-1] if event_uri else ""
        start_time     = ""
        end_time       = ""
        if event_uuid:
            import urllib.request as _ur, json as _json, os as _os
            _req = _ur.Request(
                f"https://api.calendly.com/scheduled_events/{event_uuid}",
                headers={"Authorization": f"Bearer {_os.getenv('CALENDLY_TOKEN', '')}"}
            )
            try:
                with _ur.urlopen(_req) as _r:
                    _ev = _json.loads(_r.read())["resource"]
                    start_time = _ev.get("start_time", "")
                    end_time   = _ev.get("end_time", "")
            except Exception as _e:
                print(f"[calendly] WARNING recuperation evenement {event_uuid}: {_e}")
        scheduling_url = payload.get("invitee", {}).get("reschedule_url", "")

        print(f"[calendly] Annulation détectée — {len(waitlist)} personne(s) à notifier")
        notifier.notify_all(waitlist, event_name=event_name, start_time=start_time, end_time=end_time, booking_url=scheduling_url)

        save_waitlist([])
        return jsonify({"status": "notified", "count": len(waitlist)}), 200
    except Exception as exc:
        import traceback
        print(f"[calendly] ERROR traitement webhook: {exc}")
        return jsonify({"status": "error", "detail": str(exc)}), 200


@app.route("/unsubscribe", methods=["GET"])
def unsubscribe():
    email = request.args.get("email", "").strip().lower()
    if not email:
        return "<p>Email manquant.</p>", 400
    waitlist = load_waitlist()
    new_waitlist = [e for e in waitlist if e.get("email") != email]
    if len(new_waitlist) < len(waitlist):
        save_waitlist(new_waitlist)
        print(f"[unsubscribe] {email} retiré de la liste d'attente")
    return """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Désinscription confirmée</title>
  <style>
    body{margin:0;padding:40px 20px;background:#F8EFE2;font-family:Arial,sans-serif;text-align:center}
    .box{max-width:480px;margin:0 auto;background:#fff;border-radius:10px;padding:40px 32px;box-shadow:0 2px 8px rgba(0,0,0,.1)}
    h1{color:#419958;font-size:22px;margin:0 0 16px}
    p{color:#333;font-size:15px;line-height:1.6}
  </style>
</head>
<body>
  <div class="box">
    <h1>Désinscription confirmée</h1>
    <p>Votre adresse a bien été retirée de la liste d'attente.<br>Vous ne recevrez plus de notifications.</p>
  </div>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
