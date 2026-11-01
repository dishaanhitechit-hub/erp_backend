"""WhatsApp alert for pings.

Every ping also goes to the receiver's WhatsApp (users.wp_mobile) through the
existing template sender, which runs in the background, never raises, and
logs each attempt in whatsapp_log.

Needs an approved Meta template (default name "erp_ping_alert", language
English "en") with these named body parameters:
    {{sender_name}}  {{ping_type}}  {{details}}  {{erp_link}}

.env (all optional):
    WHATSAPP_PING_TEMPLATE=erp_ping_alert   # template name
    WHATSAPP_PING_ENABLED=false             # switch the alert off
    FRONTEND_BASE_URL=https://132.154.156.82
"""
import os
import re

from app.modules.communication.whatsapp_service import send_template

_DEFAULT_LINK = "https://132.154.156.82"


def _clean(text, limit=300) -> str:
    """WhatsApp template values may not contain newlines/tabs or long runs of
    spaces, and must not be empty."""
    text = re.sub(r"[\r\n\t]+", " ", str(text or ""))
    text = re.sub(r" {4,}", "   ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "-"


def module_label(module_code: str) -> str:
    return (module_code or "").replace("_", " ").title()


def notify_ping(receiver, sender_name: str, ping_label: str, details: str,
                ping_id=None, module_code: str = None) -> None:
    """Send the WhatsApp alert for one ping. Never raises."""
    try:
        if os.getenv("WHATSAPP_PING_ENABLED", "true").lower() in ("0", "false", "no"):
            return
        phone = getattr(receiver, "wp_mobile", None)
        if not phone:
            return
        send_template(
            phone         = phone,
            template_name = os.getenv("WHATSAPP_PING_TEMPLATE", "erp_ping_alert"),
            body_params   = {
                "sender_name": _clean(sender_name, 60),
                "ping_type":   _clean(ping_label, 40),
                "details":     _clean(details),
                "erp_link":    (os.getenv("FRONTEND_BASE_URL") or _DEFAULT_LINK).rstrip("/"),
            },
            module_code   = module_code or "comm_ping",
            record_id     = ping_id,
            event         = "ping",
        )
    except Exception:
        pass
