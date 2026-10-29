import os
import threading
import requests
from datetime import datetime

from app.extensions import db
from app.models.whatsapp_log import WhatsappLog

_GRAPH_BASE = "https://graph.facebook.com"

_ACTION_BUTTONS = [
    {"index": "0", "payload": "WA_APPROVE"},
    {"index": "1", "payload": "WA_REBACK"},
    {"index": "2", "payload": "WA_REJECT"},
]


def normalize_phone(phone: str) -> str | None:
    if not phone:
        return None
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone:
        return None
    if phone.startswith("+"):
        return phone
    if phone.startswith("91") and len(phone) == 12:
        return "+" + phone
    if len(phone) == 10:
        return "+91" + phone
    return "+" + phone


def _build_template_payload(to: str, template_name: str, body_params: dict,
                             pdf_url: str, doc_no: str, has_buttons: bool) -> dict:
    components = []

    # Header: document attachment (PDF)
    # Body: named parameters
    if body_params:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "parameter_name": k, "text": str(v)}
                for k, v in body_params.items()
            ]
        })

    # Buttons: Approve / Send Back / Reject
    if has_buttons:
        for btn in _ACTION_BUTTONS:
            components.append({
                "type": "button",
                "sub_type": "quick_reply",
                "index": btn["index"],
                "parameters": [{"type": "payload", "payload": btn["payload"]}]
            })

    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components
        }
    }


def _do_send(phone: str, template_name: str, body_params: dict, pdf_url: str,
             doc_no: str, has_buttons: bool, module_code: str, record_id,
             project_code: str, event: str):
    token = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    version = os.getenv("WHATSAPP_API_VERSION", "v21.0")

    log = WhatsappLog(
        phone=phone,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event=event,
        message_text=template_name,
        status="failed",
        sent_at=datetime.utcnow(),
    )

    try:
        url = f"{_GRAPH_BASE}/{version}/{phone_number_id}/messages"
        payload = _build_template_payload(phone, template_name, body_params,
                                          pdf_url, doc_no, has_buttons)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()

        if resp.ok and data.get("messages"):
            log.status = "sent"
            log.wa_message_id = data["messages"][0].get("id")
        else:
            log.error_msg = str(data)

    except Exception as exc:
        log.error_msg = str(exc)

    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            db.session.add(log)
            db.session.commit()
    except Exception:
        pass


def send_template(phone: str, template_name: str, body_params: dict,
                  pdf_url: str = None, doc_no: str = "",
                  has_buttons: bool = False, module_code: str = None,
                  record_id=None, project_code: str = None, event: str = None):
    """Fire-and-forget template message. Never raises."""
    try:
        normalized = normalize_phone(phone)
        if not normalized:
            return
        t = threading.Thread(
            target=_do_send,
            args=(normalized, template_name, body_params, pdf_url,
                  doc_no, has_buttons, module_code, record_id, project_code, event),
            daemon=True,
        )
        t.start()
    except Exception:
        pass


def send_otp(phone: str, otp: str):
    """Send authentication OTP via WhatsApp. Never raises."""
    try:
        normalized = normalize_phone(phone)
        if not normalized:
            return
        token = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        version = os.getenv("WHATSAPP_API_VERSION", "v21.0")
        url = f"{_GRAPH_BASE}/{version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized,
            "type": "template",
            "template": {
                "name": "otp_forgot_password",
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": otp}],
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [{"type": "text", "text": otp}],
                    },
                ],
            },
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception:
        pass


def send_text_reply(phone: str, message: str):
    """
    Free-text reply — only valid within 24h after user initiates.
    Used for webhook confirmations. Never raises.
    """
    try:
        normalized = normalize_phone(phone)
        if not normalized:
            return
        token = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        version = os.getenv("WHATSAPP_API_VERSION", "v21.0")
        url = f"{_GRAPH_BASE}/{version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized,
            "type": "text",
            "text": {"body": message}
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception:
        pass
