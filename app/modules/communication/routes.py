import os
from flask import Blueprint, request, jsonify
from app.modules.communication.whatsapp_webhook import handle_webhook

wa_bp = Blueprint("whatsapp", __name__)


@wa_bp.get("/webhook/whatsapp")
def verify():
    """Meta webhook verification — called once during setup."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == os.getenv("WHATSAPP_VERIFY_TOKEN"):
        return challenge, 200
    return jsonify({"error": "Forbidden"}), 403


@wa_bp.post("/webhook/whatsapp")
def receive():
    """Receive incoming messages from Meta. Must always return 200."""
    data = request.get_json(silent=True) or {}
    handle_webhook(data)
    return jsonify({"status": "ok"}), 200
