"""
WhatsApp notifications for the cascading delete system.

Two events:
  1. delete_request_raised   — sent to managers of blocking child modules
  2. delete_completed        — sent to the original requester when parent is deleted

Template names (must be created in Meta Business Manager):
  - erp_delete_request      : notifies downstream manager to clear their records
  - erp_delete_completed    : notifies requester that deletion is done
"""

from app.modules.communication.whatsapp_service import send_template
from .dependency_map import get_display_name


# ── Who to notify per blocking module ─────────────────────────────────────
# Maps module_code → project role name that should receive the WA notification.
# The service looks up users with that designation on the same project.
# Adjust these role names to match what is in your `designations` table.

MODULE_NOTIFICATION_ROLE = {
    "ORDER":                "Order Manager",
    "PW_ORDER":             "Project Work Order Manager",
    "GRN":                  "GRN Manager",
    "SRN":                  "SRN Manager",
    "GIN":                  "Store Manager",
    "DC":                   "Store Manager",
    "DLR":                  "Site Manager",
    "BVS":                  "Billing Manager",
    "BSS":                  "Billing Manager",
    "BRR":                  "Billing Manager",
    "BRG":                  "Billing Manager",
    "BRS":                  "Billing Manager",
    "BRB":                  "Billing Manager",
    "PURCHASE_BILL":        "Accounts",
    "BILL_PAYMENT":         "Accounts Head",
    "PURCHASE_VOUCHER":     "Accounts",
    "PAYMENT_VOUCHER":      "Accounts Head",
    "SALE_BILL":            "Accounts",
    "SALE_RECEIPT":         "Accounts",
    "SALE_RECEIPT_BILLING": "Accounts Head",
    "OG_SALE_ORDER":        "Billing Manager",
    "BILLING":              "Billing Manager",
    "PETTY_CASH_BUDGET":    "Site Manager",
    "PETTY_CASH_VOUCHER":   "Finance Head",
    "JOURNAL_ENTRY":        "Finance Head",
    "CONTRA_ENTRY":         "Finance Head",
    "CREDIT_NOTE":          "Finance Head",
    "DEBIT_NOTE":           "Finance Head",
    "BBS_REGISTER":         "Site Engineer",
    "DRAWING_REGISTER":     "Site Engineer",
    "HINDRANCE_REGISTER":   "Site Manager",
    "CONCRETE_REGISTRY":    "Site Engineer",
    "BATCHING_PLANT":       "Plant Manager",
    "UNCERTAIN_ALLOCATION": "Billing Manager",
}


def _get_phones_for_module(module_code: str, project_code: str) -> list[str]:
    """
    Fetch WA phone numbers for users who should be notified about a
    blocking module.  Uses the project role → designation lookup.
    Returns a list of normalized phone strings (may be empty).
    """
    if not project_code:
        return []

    role_name = MODULE_NOTIFICATION_ROLE.get(module_code)
    if not role_name:
        return []

    try:
        from app.models.project_role import ProjectUserRole
        from app.models.designation import Designation
        from app.models.user import User

        rows = (
            ProjectUserRole.query
            .join(Designation, Designation.id == ProjectUserRole.designation_id)
            .join(User, User.id == ProjectUserRole.user_id)
            .filter(
                ProjectUserRole.project_id.in_(
                    # resolve project_code → project.id
                    _project_ids_for_code(project_code)
                ),
                Designation.designation_name.ilike(f"%{role_name}%"),
            )
            .all()
        )

        from app.modules.communication.whatsapp_service import normalize_phone
        phones = []
        for row in rows:
            if row.user and row.user.wp_mobile:
                normalized = normalize_phone(row.user.wp_mobile)
                if normalized:
                    phones.append(normalized)
        return list(set(phones))

    except Exception:
        return []


def _project_ids_for_code(project_code: str) -> list[int]:
    try:
        from app.models.project import Project
        project = Project.query.filter_by(project_code=project_code).first()
        return [project.id] if project else []
    except Exception:
        return []


def notify_delete_request_raised(
    delete_request,
    blocking: list[dict],
    requester_user,
    module_code: str,
    record_no: str,
    project_code: str,
    display_name: str,
    reason: str = "",
):
    """
    Send WhatsApp to managers of each blocking child module.
    Groups blocking docs by module_code so one message goes to each role.
    """
    requester_name = requester_user.username if requester_user else "System"

    # Group blocking docs by module_code
    by_module: dict[str, list[str]] = {}
    for b in blocking:
        by_module.setdefault(b["module_code"], []).append(b["doc_no"])

    for child_module_code, doc_nos in by_module.items():
        phones = _get_phones_for_module(child_module_code, project_code)
        if not phones:
            continue

        child_display = get_display_name(child_module_code)
        affected_str  = ", ".join(doc_nos[:5])
        if len(doc_nos) > 5:
            affected_str += f" (+{len(doc_nos) - 5} more)"

        for phone in phones:
            send_template(
                phone         = phone,
                template_name = "erp_delete_request",
                body_params   = {
                    "parent_module":  display_name,
                    "parent_doc_no":  record_no,
                    "project_code":   project_code or "",
                    "requester_name": requester_name,
                    "child_module":   child_display,
                    "affected_docs":  affected_str,
                    "reason":         reason or "Not specified",
                },
                doc_no        = record_no,
                has_buttons   = False,
                module_code   = module_code,
                record_id     = delete_request.record_id,
                project_code  = project_code,
                event         = "DELETE_REQUEST",
            )


def notify_delete_completed(
    module_code: str,
    record_no: str,
    project_code: str,
    requester_user,
):
    """
    Send WhatsApp to the original requester confirming the delete is done.
    """
    if not requester_user or not requester_user.wp_mobile:
        return

    from app.modules.communication.whatsapp_service import normalize_phone
    phone = normalize_phone(requester_user.wp_mobile)
    if not phone:
        return

    display_name = get_display_name(module_code)
    from datetime import datetime

    send_template(
        phone         = phone,
        template_name = "erp_delete_completed",
        body_params   = {
            "module_name":  display_name,
            "doc_no":       record_no,
            "project_code": project_code or "",
            "completed_at": datetime.utcnow().strftime("%d %b %Y %H:%M"),
        },
        doc_no        = record_no,
        has_buttons   = False,
        module_code   = module_code,
        record_id     = None,
        project_code  = project_code,
        event         = "DELETE_COMPLETED",
    )


def notify_delete_reminder(delete_request, project_code: str):
    """
    Reminder sent after 24h if downstream has not acted.
    Called by a scheduled job.
    """
    import json
    from datetime import datetime

    blocked_modules = json.loads(delete_request.blocked_by_modules or "[]")
    parent_display  = get_display_name(delete_request.module_code)

    pending_since = ""
    if delete_request.requested_at:
        delta = datetime.utcnow() - delete_request.requested_at
        hours = int(delta.total_seconds() / 3600)
        pending_since = f"{hours}h ago"

    for child_module_code in blocked_modules:
        phones = _get_phones_for_module(child_module_code, project_code)
        child_display = get_display_name(child_module_code)
        for phone in phones:
            send_template(
                phone         = phone,
                template_name = "erp_delete_reminder",
                body_params   = {
                    "parent_module": parent_display,
                    "parent_doc_no": delete_request.record_no or str(delete_request.record_id),
                    "project_code":  project_code or "",
                    "child_module":  child_display,
                    "pending_since": pending_since,
                },
                doc_no        = delete_request.record_no or "",
                has_buttons   = False,
                module_code   = delete_request.module_code,
                record_id     = delete_request.record_id,
                project_code  = project_code,
                event         = "DELETE_REMINDER",
            )
