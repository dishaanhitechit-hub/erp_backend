from app.modules.workflow.service import find_pending_records
from app.modules.communication.chatting import ping_service

# Modules that can be attached to an approval ping. Each needs a detail page in
# the frontend (see src/lib/moduleRegistry.js) and an entry in workflow MODULE_MAP.
# To add a module: add its code here and its route in moduleRegistry.js.
APPROVAL_PING_MODULES = [
    "indent",
    "order",
    "pw_order",
    "goods_received_note",
    "goods_issue_note",
    "service_received_note",
    "delivery_challan",
    "concrete_registry",
    "drawing_register",
    "bill_receive_register",
    "log_sheet",
]


class ApprovalPingError(ValueError):
    pass


def project_code_for(project_id) -> str | None:
    """The JWT's `projectId` claim is the project's numeric id, but workflow
    tables are keyed by the project_code string — translate between them."""
    from app.extensions import db
    from app.models.project import Project

    if project_id in (None, ""):
        return None
    try:
        project = db.session.get(Project, int(project_id))
    except (TypeError, ValueError):
        return None
    return project.project_code if project else None


def _check(module_code: str, project_code: str):
    if module_code not in APPROVAL_PING_MODULES:
        raise ApprovalPingError("This module can't be used for approval pings")
    if not project_code:
        raise ApprovalPingError("No project selected — open a project first")


def pending_for_user(module_code: str, project_code: str, target_user_id: int) -> list:
    _check(module_code, project_code)
    return find_pending_records(module_code, project_code, target_user_id)


def send_approval_pings(
    sender_id:    int,
    receiver_id:  int,
    module_code:  str,
    record_ids:   list,
    project_code: str,
    message:      str = None,
) -> list:
    """One ping per record. Only records that are actually waiting on the
    receiver's approval are accepted, so a ping can't point at arbitrary records."""
    _check(module_code, project_code)
    if receiver_id == sender_id:
        raise ApprovalPingError("You can't send an approval ping to yourself")

    wanted  = {int(r) for r in record_ids or []}
    if not wanted:
        raise ApprovalPingError("Select at least one record")

    pending = {r["id"]: r for r in find_pending_records(module_code, project_code, receiver_id)}
    valid   = [pending[rid] for rid in wanted if rid in pending]
    if not valid:
        raise ApprovalPingError("None of the selected records are pending for this person")

    sent = []
    for rec in valid:
        ping = ping_service.send_ping(
            sender_id          = sender_id,
            receiver_id        = receiver_id,
            ping_type          = "approval_request",
            message            = (message or "").strip()[:500] or None,
            context_module     = module_code,
            context_record_id  = rec["id"],
            context_record_ref = (rec["recordNo"] or str(rec["id"]))[:100],
        )
        sent.append({"pingId": ping.id, "recordId": rec["id"], "recordNo": rec["recordNo"]})
    return sent


# ── Record status on approval pings ──────────────────────────────────────────
# recordStatus, from the receiver's point of view:
#   pending  – still waiting on the receiver's approval
#   approved – passed the receiver's stage (approved there, or fully approved)
#   rejected / returned (sent back or back in draft) / removed (record deleted)

def _status_for(record, approval_code, receiver_id, path_cache) -> str | None:
    from app.models.approval_path import ApprovalPath

    if record is None:
        return "removed"
    ws = record.workflow_status or ""
    if ws.startswith("Pending_L"):
        try:
            level = int(ws[len("Pending_L"):])
        except ValueError:
            return None
        projects = tuple(sorted({
            c for c in (getattr(record, f, None)
                        for f in ("project_code", "to_project_code", "from_project_code")) if c
        }))
        key = (projects, approval_code, receiver_id, level)
        if key not in path_cache:
            path_cache[key] = bool(projects) and ApprovalPath.query.filter(
                ApprovalPath.project_code.in_(projects),
                ApprovalPath.module_code == approval_code,
                ApprovalPath.user_id     == receiver_id,
                ApprovalPath.level_no    == level,
                ApprovalPath.path_type   == "APPROVER",
            ).first() is not None
        return "pending" if path_cache[key] else "approved"
    if ws == "Approved":
        return "approved"
    if ws == "Rejected":
        return "rejected"
    if ws in ("Reback", "Rebacked", "Draft"):
        return "returned"
    return None


def add_record_status(pings: list) -> list:
    """Adds `recordStatus` and `recordWorkflowStatus` to approval pings in a
    ping list (dicts from ping_service). Other pings are left untouched."""
    from app.modules.workflow.service import MODULE_MAP
    from app.alias_helper import get_approval_module

    by_module = {}
    for p in pings:
        if p.get("pingType") == "approval_request" and p.get("contextModule") in MODULE_MAP \
                and p.get("contextRecordId"):
            by_module.setdefault(p["contextModule"], []).append(p)

    path_cache = {}
    for module_code, items in by_module.items():
        Model   = MODULE_MAP[module_code]["model"]
        ids     = {int(p["contextRecordId"]) for p in items}
        records = {r.id: r for r in Model.query.filter(Model.id.in_(ids)).all()}
        approval_code = get_approval_module(module_code)
        for p in items:
            rec = records.get(int(p["contextRecordId"]))
            p["recordStatus"]         = _status_for(rec, approval_code, p["receiverId"], path_cache)
            p["recordWorkflowStatus"] = rec.workflow_status if rec else None
    return pings
