"""
Handles incoming WhatsApp messages from Meta webhook.
Button taps → direct approve / ask-for-reason flow
Text replies → complete reback/reject with reason
"""
import importlib
from app.extensions import db
from app.models.whatsapp_log import WhatsappLog
from app.models.user import User
from app.modules.communication.whatsapp_service import send_template, send_text_reply

# ---------------------------------------------------------------------------
# Service registry — maps module_code to its service import path + function names
# None means function does not exist for that module (handled gracefully)
# ---------------------------------------------------------------------------
_REGISTRY = {
    "indent": {
        "mod": "app.modules.resources.indent.service",
        "approve": "approve_indent", "reback": "reback_indent", "reject": "reject_indent",
    },
    "order": {
        "mod": "app.modules.resources.order.service",
        "approve": "approve_order", "reback": "reback_order", "reject": "reject_order",
    },
    "grn": {
        "mod": "app.modules.resources.grn.service",
        "approve": "approve_grn", "reback": "reback_grn", "reject": "reject_grn",
    },
    "gin": {
        "mod": "app.modules.resources.gin.service",
        "approve": "approve_gin", "reback": "reback_gin", "reject": "reject_gin",
    },
    "srn": {
        "mod": "app.modules.resources.srn.service",
        "approve": "approve_srn", "reback": "reback_srn", "reject": "reject_srn",
    },
    "dc": {
        "mod": "app.modules.resources.dc.service",
        "approve": "approve_dc", "reback": "reback_dc", "reject": "reject_dc",
    },
    "dlr": {
        "mod": "app.modules.resources.dlr.service",
        "approve": "approve_dlr", "reback": "reback_dlr", "reject": "reject_dlr",
        "needs_project": True,  # approve_dlr(id, user_id, project_code, comments)
    },
    "pw_order": {
        "mod": "app.modules.resources.order_projectwork.service",
        "approve": "approve_pw_order", "reback": "reback_pw_order", "reject": "reject_pw_order",
    },
    "bvs": {
        "mod": "app.modules.resources.vendor_billing_grn.service",
        "approve": "approve_bvs", "reback": "reback_bvs", "reject": "reject_bvs",
    },
    "bss": {
        "mod": "app.modules.resources.vendor_billing_srn.service",
        "approve": "approve_bss", "reback": "reback_bss", "reject": "reject_bss",
    },
    "batching_plant": {
        "mod": "app.modules.resources.batching_plant.service",
        "approve": "approve_batching_plant", "reback": "reback_batching_plant",
        "reject": "reject_batching_plant",
    },
    "brr": {
        "mod": "app.modules.billing.bill_receive_register.service",
        "approve": "approve_brr", "reback": "reback_brr", "reject": "reject_brr",
    },
    "brb": {
        "mod": "app.modules.billing.brr_billing.service",
        "approve": "approve_brb", "reback": "reback_brb", "reject": "reject_brb",
    },
    "brg": {
        "mod": "app.modules.billing.brr_billing_grn.service",
        "approve": "approve_brg", "reback": "reback_brg", "reject": "reject_brg",
    },
    "brs": {
        "mod": "app.modules.billing.brr_billing_srn.service",
        "approve": "approve_brs", "reback": "reback_brs", "reject": "reject_brs",
    },
    "purchase_bill": {
        "mod": "app.modules.finance.purchase_bill.service",
        "approve": "approve_purchase_bill", "reback": "reback_purchase_bill",
        "reject": "reject_purchase_bill",
    },
    "sale_bill": {
        "mod": "app.modules.finance.sale_bill.service",
        "approve": "approve_sale_bill", "reback": "reback_sale_bill",
        "reject": "reject_sale_bill",
    },
    "payment_voucher": {
        "mod": "app.modules.finance.payment_voucher.service",
        "approve": "approve_payment_voucher", "reback": "reback_payment_voucher",
        "reject": "reject_payment_voucher",
    },
    "bill_payment_receipt": {
        "mod": "app.modules.finance.bill_payment.service",
        "approve": "approve_bill_payment", "reback": "reback_bill_payment",
        "reject": "reject_bill_payment",
    },
    "purchase_voucher": {
        "mod": "app.modules.finance.purchase_voucher.service",
        "approve": "approve_purchase_voucher", "reback": "reback_purchase_voucher",
        "reject": "reject_purchase_voucher",
    },
    "budget": {
        "mod": "app.modules.project_mgmt.contract.budget.service",
        "approve": "approve_budget", "reback": "reback_budget", "reject": "reject_budget",
    },
    "drawing_register": {
        "mod": "app.modules.project_mgmt.register.drawing_register.service",
        "approve": "approve_drawing_register", "reback": "reback_drawing_register",
        "reject": "reject_drawing_register",
    },
    "bbs_register": {
        "mod": "app.modules.project_mgmt.register.bbs_register.service",
        "approve": "approve_bbs_register", "reback": "reback_bbs_register",
        "reject": "reject_bbs_register",
    },
    "hindrance_register": {
        "mod": "app.modules.project_mgmt.register.hindrance_register.service",
        "approve": "approve_hindrance_register", "reback": "reback_hindrance_register",
        "reject": "reject_hindrance_register",
    },
    "concrete_registry": {
        # NOTE: functions are named approve_registry / reback_registry
        "mod": "app.modules.project_mgmt.register.concrete_registry.service",
        "approve": "approve_registry", "reback": "reback_registry", "reject": "reject_registry",
    },
    "billing": {
        "mod": "app.modules.project_mgmt.custom_billing.billing.service",
        "approve": "approve_billing", "reback": "reback_billing", "reject": "reject_billing",
    },
    "og_sale_order": {
        "mod": "app.modules.project_mgmt.custom_billing.og_sale_order.service",
        "approve": "approve_og_sale_order", "reback": "reback_og_sale_order",
        "reject": "reject_og_sale_order",
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_from_phone(phone: str) -> str:
    """Ensure +91 prefix for matching against DB."""
    from app.modules.communication.whatsapp_service import normalize_phone
    return normalize_phone(phone) or phone


def _get_user_by_phone(phone: str):
    normalized = _normalize_from_phone(phone)
    # Try with + prefix and without
    user = User.query.filter(User.wp_mobile == normalized).first()
    if not user:
        user = User.query.filter(User.wp_mobile == normalized.lstrip("+")).first()
    if not user and normalized.startswith("+91"):
        user = User.query.filter(User.wp_mobile == normalized[3:]).first()
    return user


def _call_service(module_code: str, action: str, record_id: int,
                  user_id: int, project_code: str = None, comments: str = None):
    """Dynamically call approve/reback/reject for any module."""
    reg = _REGISTRY.get(module_code)
    if not reg:
        return None, f"Module '{module_code}' not in registry"

    func_name = reg.get(action)
    if not func_name:
        return None, f"Action '{action}' not available for module '{module_code}'"

    try:
        svc = importlib.import_module(reg["mod"])
        func = getattr(svc, func_name, None)
        if not func:
            return None, f"Function '{func_name}' not found in service"

        # DLR needs project_code as 3rd positional arg
        if reg.get("needs_project") and action in ("approve", "reback", "reject"):
            result = func(record_id, user_id, project_code, comments)
        elif action == "approve":
            result = func(record_id, approved_by=user_id, comments=comments)
        elif action == "reback":
            result = func(record_id, reback_by=user_id, comments=comments)
        elif action == "reject":
            result = func(record_id, rejected_by=user_id, comments=comments)
        else:
            return None, "Unknown action"

        return result, None

    except Exception as e:
        return None, str(e)


def _store_pending(phone: str, module_code: str, record_id: int,
                   project_code: str, event: str):
    """Store pending reback/reject state waiting for reason text."""
    # Clear any previous pending for this phone
    WhatsappLog.query.filter_by(phone=phone, status="pending").delete()

    row = WhatsappLog(
        phone=phone,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event=event,      # PENDING_REBACK or PENDING_REJECT
        status="pending",
    )
    db.session.add(row)
    db.session.commit()


def _send_ask_reason(phone: str, action_word: str, doc_no: str):
    send_template(
        phone=phone,
        template_name="erp_ask_reason",
        body_params={"action_word": action_word, "doc_no": doc_no},
        pdf_url=None,
        doc_no=doc_no,
        has_buttons=False,
        event="ASK_REASON",
    )


# ---------------------------------------------------------------------------
# Button reply handler
# ---------------------------------------------------------------------------

def _handle_button_reply(from_phone: str, button_payload: str, context_message_id: str):
    """Called when approver taps Approve / Send Back / Reject."""

    # Find the original outbound log by wa_message_id
    log = WhatsappLog.query.filter_by(wa_message_id=context_message_id).first()
    if not log:
        send_text_reply(from_phone, "Sorry, could not find the document for this action. Please use the ERP link.")
        return

    user = _get_user_by_phone(from_phone)
    if not user:
        send_text_reply(from_phone, "Your WhatsApp number is not registered in the ERP system.")
        return

    module_code = log.module_code
    record_id = log.record_id
    project_code = log.project_code

    if button_payload == "WA_APPROVE":
        result, err = _call_service(module_code, "approve", record_id, user.id, project_code)
        if err:
            send_text_reply(from_phone, f"Could not approve: {err}")
        else:
            send_text_reply(from_phone, f"✅ Approved successfully.")

    elif button_payload == "WA_REBACK":
        _store_pending(from_phone, module_code, record_id, project_code, "PENDING_REBACK")
        _send_ask_reason(from_phone, "sending back", log.message_text or "document")

    elif button_payload == "WA_REJECT":
        _store_pending(from_phone, module_code, record_id, project_code, "PENDING_REJECT")
        _send_ask_reason(from_phone, "rejecting", log.message_text or "document")


# ---------------------------------------------------------------------------
# Text reply handler (reason for reback/reject)
# ---------------------------------------------------------------------------

def _handle_text_reply(from_phone: str, text_body: str):
    """Called when approver sends a free-text reply (reason for reback/reject)."""

    pending = (
        WhatsappLog.query
        .filter_by(phone=from_phone, status="pending")
        .order_by(WhatsappLog.id.desc())
        .first()
    )

    if not pending:
        # Ignore unknown text messages
        return

    user = _get_user_by_phone(from_phone)
    if not user:
        send_text_reply(from_phone, "Your number is not registered in the ERP system.")
        return

    action = "reback" if pending.event == "PENDING_REBACK" else "reject"
    module_code = pending.module_code
    record_id = pending.record_id
    project_code = pending.project_code
    comments = text_body.strip()

    # Clear pending state before calling service (service may trigger new WA messages)
    pending.status = "done"
    db.session.commit()

    result, err = _call_service(module_code, action, record_id, user.id,
                                project_code, comments=comments)
    if err:
        send_text_reply(from_phone, f"Could not process: {err}")
    else:
        action_label = "Sent back" if action == "reback" else "Rejected"
        send_text_reply(from_phone, f"🔄 {action_label} successfully. Reason recorded.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def handle_webhook(data: dict):
    """
    Parse Meta webhook payload and route to button or text handler.
    Called from the route handler. Never raises.
    """
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_phone = msg.get("from", "")
                    msg_type = msg.get("type", "")

                    if msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        if interactive.get("type") == "button_reply":
                            btn = interactive["button_reply"]
                            context_id = msg.get("context", {}).get("id", "")
                            _handle_button_reply(from_phone, btn.get("id", ""), context_id)

                    elif msg_type == "text":
                        body = msg.get("text", {}).get("body", "")
                        _handle_text_reply(from_phone, body)

    except Exception:
        pass  # webhook errors must never return 500 to Meta
