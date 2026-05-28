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

    return jsonify({"status": "added"}), 200


@app.route("/calendly", methods=["POST"])
def calendly_webhook():
    body  = request.get_json(silent=True) or {}
    event = body.get("event", "")

    if event != "invitee.canceled":
        return jsonify({"status": "ignored"}), 200

    waitlist = load_waitlist()
    if not waitlist:
        return jsonify({"status": "waitlist_empty"}), 200

    payload    = body.get("payload", {})
    event_name = payload.get("event_type", {}).get("name", "")
    scheduled  = payload.get("scheduled_event", {})
    start_time = scheduled.get("start_time", "")
    end_time   = scheduled.get("end_time", "")

    print(f"[calendly] Annulation détectée — {len(waitlist)} personne(s) à notifier")
    notifier.notify_all(waitlist, event_name=event_name, start_time=start_time, end_time=end_time)

    save_waitlist([])
    return jsonify({"status": "notified", "count": len(waitlist)}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
