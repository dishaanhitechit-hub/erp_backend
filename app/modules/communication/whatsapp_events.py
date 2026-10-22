"""
WhatsApp event helpers — call AFTER db.session.commit() in every workflow service.
All functions are safe to call even when phones are None — they skip silently.
"""
import os
from app.modules.communication.whatsapp_service import send_template

MODULE_NAMES = {
    "indent": "Indent",
    "order": "Purchase Order",
    "grn": "GRN",
    "gin": "GIN",
    "srn": "SRN",
    "dc": "Delivery Challan",
    "dlr": "DLR",
    "pw_order": "Project Work Order",
    "bvs": "BVS",
    "bss": "BSS",
    "batching_plant": "Batching Plant",
    "brr": "BRR",
    "brb": "BRB",
    "brg": "BRG",
    "brs": "BRS",
    "purchase_bill": "Purchase Bill",
    "sale_bill": "Sale Bill",
    "payment_voucher": "Payment Voucher",
    "bill_payment_receipt": "Bill Payment Receipt",
    "purchase_voucher": "Purchase Voucher",
    "budget": "Budget",
    "drawing_register": "Drawing Register",
    "bbs_register": "BBS Register",
    "hindrance_register": "Hindrance Register",
    "concrete_registry": "Concrete Registry",
    "machinery_log_book": "Machinery Log Book",
    "log_book_entry": "Log Book Entry",
    "billing": "Billing",
    "og_sale_order": "OG Sale Order",
}


def _name(module_code: str) -> str:
    return MODULE_NAMES.get(module_code, module_code.replace("_", " ").title())


_PRINT_SLUG = {
    "indent": "indent",
    "order": "order",
    "grn": "grn",
    "gin": "gin",
    "srn": "srn",
    "dc": "dc",
    "dlr": "dlr",
    "pw_order": "pw-order",
    "bvs": "bvs",
    "bss": "bss",
    "batching_plant": "batching-plant",
    "brr": "brr",
    "brb": "brb",
    "brg": "brg",
    "brs": "brs",
    "purchase_bill": "purchase-bill",
    "sale_bill": "sale-bill",
    "payment_voucher": "payment-voucher",
    "bill_payment_receipt": "payment",
    "purchase_voucher": "purchase-voucher",
    "budget": "budget",
    "drawing_register": "drawing-register",
    "bbs_register": "bbs-register",
    "hindrance_register": "hindrance-register",
    "concrete_registry": "concrete-registry",
    "billing": "billing",
    "og_sale_order": "og-sale-order",
}

_PRINT_BASE = "http://132.154.156.82/print"


def _base() -> str:
    return (os.getenv("FRONTEND_BASE_URL") or "").rstrip("/")


def _phone(user) -> str | None:
    if user is None:
        return None
    return getattr(user, "wp_mobile", None) or None


def _pdf_url(module_code: str, uuid: str) -> str:
    slug = _PRINT_SLUG.get(module_code, module_code.replace("_", "-"))
    return f"{_PRINT_BASE}/{slug}/{uuid}"


def _action_url(module_code: str, uuid: str) -> str:
    return f"{_base()}/{module_code}/{uuid}"


# ---------------------------------------------------------------------------
# SUBMIT → notify L1 approver (action template with buttons)
# ---------------------------------------------------------------------------
def on_submit(module_code, doc_no, uuid, project_code,
              submitter_name, approver_user, current_level, record_id=None):
    phone = _phone(approver_user)
    if not phone:
        return
    send_template(
        phone=phone,
        template_name="erp_action_required",
        body_params={
            "module_name": _name(module_code),
            "doc_no": doc_no,
            "project_code": project_code,
            "actor_name": submitter_name,
            "current_level": str(current_level),
            "pdf_url": _pdf_url(module_code, uuid),
            "action_url": _action_url(module_code, uuid),
        },
        pdf_url=_pdf_url(module_code, uuid),
        doc_no=doc_no,
        has_buttons=True,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event="SUBMIT",
    )


# ---------------------------------------------------------------------------
# APPROVE (intermediate) → notify next-level approver (action template with buttons)
# ---------------------------------------------------------------------------
def on_approve(module_code, doc_no, uuid, project_code,
               approver_name, prev_level, next_approver_user, next_level, record_id=None):
    phone = _phone(next_approver_user)
    if not phone:
        return
    send_template(
        phone=phone,
        template_name="erp_action_required",
        body_params={
            "module_name": _name(module_code),
            "doc_no": doc_no,
            "project_code": project_code,
            "actor_name": f"{approver_name} (L{prev_level} approved)",
            "current_level": str(next_level),
            "pdf_url": _pdf_url(module_code, uuid),
            "action_url": _action_url(module_code, uuid),
        },
        pdf_url=_pdf_url(module_code, uuid),
        doc_no=doc_no,
        has_buttons=True,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event="APPROVE",
    )


# ---------------------------------------------------------------------------
# FINAL_APPROVE → notify creator + optional external stakeholder
# ---------------------------------------------------------------------------
def on_final_approve(module_code, doc_no, uuid, project_code,
                     approver_name, creator_user, record_id=None,
                     external_phone=None, extra_detail=None):
    params = {
        "module_name": _name(module_code),
        "doc_no": doc_no,
        "project_code": project_code,
        "approver_name": approver_name,
        "pdf_url": _pdf_url(module_code, uuid),
        "action_url": _action_url(module_code, uuid),
    }

    phone = _phone(creator_user)
    if phone:
        send_template(
            phone=phone,
            template_name="erp_final_approved",
            body_params=params,
            pdf_url=_pdf_url(module_code, uuid),
            doc_no=doc_no,
            has_buttons=False,
            module_code=module_code,
            record_id=record_id,
            project_code=project_code,
            event="FINAL_APPROVE",
        )

    if external_phone:
        send_template(
            phone=external_phone,
            template_name="erp_final_approved",
            body_params=params,
            pdf_url=_pdf_url(module_code, uuid),
            doc_no=doc_no,
            has_buttons=False,
            module_code=module_code,
            record_id=record_id,
            project_code=project_code,
            event="FINAL_APPROVE",
        )


# ---------------------------------------------------------------------------
# REBACK → notify creator
# ---------------------------------------------------------------------------
def on_reback(module_code, doc_no, uuid, project_code,
              approver_name, creator_user, comments, record_id=None):
    phone = _phone(creator_user)
    if not phone:
        return
    send_template(
        phone=phone,
        template_name="erp_sent_back",
        body_params={
            "module_name": _name(module_code),
            "doc_no": doc_no,
            "project_code": project_code,
            "approver_name": approver_name,
            "comments": comments or "—",
            "pdf_url": _pdf_url(module_code, uuid),
            "action_url": _action_url(module_code, uuid),
        },
        pdf_url=_pdf_url(module_code, uuid),
        doc_no=doc_no,
        has_buttons=False,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event="REBACK",
    )


# ---------------------------------------------------------------------------
# REJECT → notify creator
# ---------------------------------------------------------------------------
def on_reject(module_code, doc_no, uuid, project_code,
              approver_name, creator_user, comments, record_id=None):
    phone = _phone(creator_user)
    if not phone:
        return
    send_template(
        phone=phone,
        template_name="erp_rejected",
        body_params={
            "module_name": _name(module_code),
            "doc_no": doc_no,
            "project_code": project_code,
            "approver_name": approver_name,
            "comments": comments or "—",
            "pdf_url": _pdf_url(module_code, uuid),
            "action_url": _action_url(module_code, uuid),
        },
        pdf_url=_pdf_url(module_code, uuid),
        doc_no=doc_no,
        has_buttons=False,
        module_code=module_code,
        record_id=record_id,
        project_code=project_code,
        event="REJECT",
    )


# ---------------------------------------------------------------------------
# HINDRANCE REGISTER CREATED → notify project manager instantly
# ---------------------------------------------------------------------------
def on_hindrance_created(doc_no, uuid, project_code,
                         creator_name, proj_mgmt_phone, record_id=None):
    if not proj_mgmt_phone:
        return
    send_template(
        phone=proj_mgmt_phone,
        template_name="erp_action_required",
        body_params={
            "module_name": "Hindrance Register",
            "doc_no": doc_no,
            "project_code": project_code,
            "actor_name": creator_name,
            "current_level": "1",
            "pdf_url": _pdf_url("hindrance_register", uuid),
            "action_url": _action_url("hindrance_register", uuid),
        },
        pdf_url=_pdf_url("hindrance_register", uuid),
        doc_no=doc_no,
        has_buttons=False,
        module_code="hindrance_register",
        record_id=record_id,
        project_code=project_code,
        event="CREATED",
    )
