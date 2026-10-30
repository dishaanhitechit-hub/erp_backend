"""
DeleteRequestService — core cascading delete engine.

Flow:
  1. raise_delete_request(module_code, record_id, requested_by, reason)
     → checks dependencies
     → if none: deletes immediately, returns {"status": "deleted"}
     → if blocked: creates DeleteRequest row, fires WA, returns {"status": "pending"}

  2. auto_complete_check(module_code, record_id)
     → called at the END of every module's delete service AFTER it commits
     → finds any PENDING DeleteRequest blocked by this module
     → if that parent now has no more children → deletes parent, marks COMPLETED, fires WA

  3. get_delete_request(delete_request_id) / list_delete_requests(...)
     → status queries used by routes

  4. cancel_delete_request(delete_request_id, cancelled_by)
     → marks CANCELLED
"""

import json
from datetime import datetime

from app.extensions import db
from app.models.delete_request import DeleteRequest
from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.brgMaster import BrgItem
from app.models.brbMaster import BrbItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.brsMaster import BrsItem

from .dependency_map import DEPENDENCY_MAP, get_display_name
from .whatsapp_notify import (
    notify_delete_request_raised,
    notify_delete_completed,
)


# ─── helpers ──────────────────────────────────────────────────────────────

def _get_record_no(record, config):
    """Return the human-readable doc number for a record."""
    field = config.get("doc_no_field", "id")
    return str(getattr(record, field, record.id))


def _get_project_code(record, config):
    field = config.get("project_field")
    if not field:
        return None
    return getattr(record, field, None)


def _check_indent_orders(indent_id: int) -> list[dict]:
    """
    Special check: find Orders that have items referencing this indent's items.
    Returns list of {doc_no, module_code, label} for blocking orders.
    """
    from sqlalchemy import exists
    blocking = []
    indent_item_ids = [
        r.id for r in IndentItem.query.filter_by(indent_id=indent_id).all()
    ]
    if not indent_item_ids:
        return blocking

    orders = (
        OrderMaster.query
        .join(OrderItem, OrderItem.order_id == OrderMaster.id)
        .filter(OrderItem.indent_item_id.in_(indent_item_ids))
        .distinct()
        .all()
    )
    for order in orders:
        blocking.append({
            "doc_no":      order.order_no,
            "module_code": "ORDER",
            "label":       "Purchase Order",
            "record_id":   order.id,
        })
    return blocking


def _check_grn_billing(grn_id: int) -> list[dict]:
    """
    Special check: find BRG/BRB documents that have items pointing to this GRN.
    Returns list of blocking docs.
    """
    from app.models.brgMaster import BrgMaster
    from app.models.brbMaster import BrbMaster
    blocking = []

    brg_ids = {r.brg_id for r in BrgItem.query.filter_by(grn_id=grn_id).all()}
    for brg_id in brg_ids:
        brg = BrgMaster.query.get(brg_id)
        if brg:
            blocking.append({
                "doc_no":      brg.brg_no,
                "module_code": "BRG",
                "label":       "BRG (BRR Billing GRN)",
                "record_id":   brg.id,
            })

    brb_ids = {r.brb_id for r in BrbItem.query.filter(BrbItem.grn_id == grn_id).all()}
    for brb_id in brb_ids:
        brb = BrbMaster.query.get(brb_id)
        if brb:
            blocking.append({
                "doc_no":      brb.brb_no,
                "module_code": "BRB",
                "label":       "BRB (BRR Billing)",
                "record_id":   brb.id,
            })
    return blocking


def _check_srn_billing(srn_id: int) -> list[dict]:
    """
    Special check: find BRS/BRB documents that have items pointing to this SRN.
    """
    from app.models.brsMaster import BrsMaster
    from app.models.brbMaster import BrbMaster
    blocking = []

    brs_ids = {r.brs_id for r in BrsItem.query.filter_by(srn_id=srn_id).all()}
    for brs_id in brs_ids:
        brs = BrsMaster.query.get(brs_id)
        if brs:
            blocking.append({
                "doc_no":      brs.brs_no,
                "module_code": "BRS",
                "label":       "BRS (BRR Billing SRN)",
                "record_id":   brs.id,
            })

    brb_ids = {r.brb_id for r in BrbItem.query.filter(BrbItem.srn_id == srn_id).all()}
    for brb_id in brb_ids:
        brb = BrbMaster.query.get(brb_id)
        if brb:
            blocking.append({
                "doc_no":      brb.brb_no,
                "module_code": "BRB",
                "label":       "BRB (BRR Billing)",
                "record_id":   brb.id,
            })
    return blocking


def _run_special_checks(module_code: str, record_id: int, config: dict) -> list[dict]:
    """Run any special FK checks that can't be expressed as simple column checks."""
    blocking = []
    for check_name in config.get("special_checks", []):
        if check_name == "indent_orders":
            blocking.extend(_check_indent_orders(record_id))
        elif check_name == "grn_billing":
            blocking.extend(_check_grn_billing(record_id))
        elif check_name == "srn_billing":
            blocking.extend(_check_srn_billing(record_id))
    return blocking


def _check_children(module_code: str, record_id: int, config: dict) -> list[dict]:
    """
    Query every child table defined in the config.
    Returns a list of blocking child docs: [{doc_no, module_code, label, record_id}]
    """
    blocking = []

    for child_def in config.get("children", []):
        child_model = child_def["child_model"]
        fk_col      = child_def["fk_column"]
        doc_field   = child_def["doc_no_field"]
        mod_code    = child_def["module_code"]
        label       = child_def["label"]

        children = child_model.query.filter(
            getattr(child_model, fk_col) == record_id
        ).all()

        for child in children:
            blocking.append({
                "doc_no":      str(getattr(child, doc_field, child.id)),
                "module_code": mod_code,
                "label":       label,
                "record_id":   child.id,
            })

    # Run any special checks (indent→order via items, grn→brg via items, etc.)
    blocking.extend(_run_special_checks(module_code, record_id, config))

    return blocking


def _do_delete_record(module_code: str, record_id: int, config: dict):
    """
    Actually delete the record and its ORM-cascade children.
    The model's cascade="all,delete-orphan" on relationships handles item rows.
    """
    model_class = config["model_class"]
    record = model_class.query.get(record_id)
    if record:
        db.session.delete(record)
        db.session.commit()


# ─── public API ───────────────────────────────────────────────────────────

def raise_delete_request(
    module_code: str,
    record_id: int,
    requested_by: int,
    reason: str = None,
) -> dict:
    """
    Entry point called from every module's route.
    Returns a dict:
      {"status": "deleted", "message": "..."}                      — immediate
      {"status": "pending", "delete_request_id": N, "blocked_by": [...], "message": "..."}
    """
    config = DEPENDENCY_MAP.get(module_code)
    if not config:
        return {"status": "error", "message": f"Unknown module: {module_code}"}, 400

    model_class = config["model_class"]
    record = model_class.query.get(record_id)
    if not record:
        return {"status": "error", "message": "Record not found"}, 404

    record_no    = _get_record_no(record, config)
    project_code = _get_project_code(record, config)
    display_name = get_display_name(module_code)

    # Check if a PENDING delete request already exists for this record
    existing = DeleteRequest.query.filter_by(
        module_code=module_code,
        record_id=record_id,
        status="PENDING",
    ).first()
    if existing:
        return {
            "status":            "pending",
            "delete_request_id": existing.id,
            "message":           f"A delete request for {display_name} {record_no} is already pending.",
            "blocked_by":        json.loads(existing.blocked_by_modules or "[]"),
        }, 200

    # Find blocking children
    blocking = _check_children(module_code, record_id, config)

    if not blocking:
        # No downstream records — delete immediately
        _do_delete_record(module_code, record_id, config)
        # Notify requester via WA that delete is done
        from app.models.user import User
        requester = User.query.get(requested_by)
        notify_delete_completed(
            module_code=module_code,
            record_no=record_no,
            project_code=project_code,
            requester_user=requester,
        )
        return {
            "status":  "deleted",
            "message": f"{display_name} {record_no} deleted successfully.",
        }, 200

    # Build blocking summary
    blocked_modules = list({b["module_code"] for b in blocking})
    blocked_docs    = ", ".join(b["doc_no"] for b in blocking[:10])  # cap at 10 for message

    # Create DeleteRequest row
    dr = DeleteRequest(
        module_code          = module_code,
        record_id            = record_id,
        record_no            = record_no,
        project_code         = project_code,
        requested_by         = requested_by,
        reason               = reason,
        status               = "PENDING",
        blocked_by_modules   = json.dumps(blocked_modules),
        blocked_by_docs      = blocked_docs,
    )
    db.session.add(dr)
    db.session.commit()

    # Send WhatsApp notification to managers of the blocking modules
    from app.models.user import User
    requester = User.query.get(requested_by)

    notify_delete_request_raised(
        delete_request   = dr,
        blocking         = blocking,
        requester_user   = requester,
        module_code      = module_code,
        record_no        = record_no,
        project_code     = project_code,
        display_name     = display_name,
        reason           = reason or "",
    )

    # Update wa_sent flag
    dr.wa_sent    = True
    dr.wa_sent_at = datetime.utcnow()
    db.session.commit()

    return {
        "status":            "pending",
        "delete_request_id": dr.id,
        "message": (
            f"Delete request raised for {display_name} {record_no}. "
            f"Waiting for {', '.join(get_display_name(m) for m in blocked_modules)} "
            f"to be deleted first."
        ),
        "blocked_by_modules": blocked_modules,
        "blocked_by_docs":    blocked_docs,
        "whatsapp_sent":      True,
    }, 202


def auto_complete_check(deleted_module_code: str, deleted_record_id: int):
    """
    Call this at the END of every module's delete service, AFTER committing.
    It checks if the deletion of this record unblocks any pending DeleteRequest.

    For each pending DR, it re-checks if the parent still has children.
    If not → auto-delete parent and mark COMPLETED.
    """
    # Find all PENDING requests that were blocked by this module type
    pending_requests = DeleteRequest.query.filter(
        DeleteRequest.status == "PENDING"
    ).all()

    for dr in pending_requests:
        # Re-evaluate blocking children for this parent record
        config = DEPENDENCY_MAP.get(dr.module_code)
        if not config:
            continue

        current_blocking = _check_children(dr.module_code, dr.record_id, config)

        if not current_blocking:
            # All children are gone — delete parent now
            _do_delete_record(dr.module_code, dr.record_id, config)

            dr.status       = "COMPLETED"
            dr.completed_at = datetime.utcnow()
            db.session.commit()

            # Notify requester
            from app.models.user import User
            requester = User.query.get(dr.requested_by)
            config_map = DEPENDENCY_MAP.get(dr.module_code, {})
            notify_delete_completed(
                module_code  = dr.module_code,
                record_no    = dr.record_no,
                project_code = dr.project_code,
                requester_user = requester,
            )
        else:
            # Update the blocked_by snapshot
            blocked_modules = list({b["module_code"] for b in current_blocking})
            blocked_docs    = ", ".join(b["doc_no"] for b in current_blocking[:10])
            dr.blocked_by_modules = json.dumps(blocked_modules)
            dr.blocked_by_docs    = blocked_docs
            db.session.commit()


def get_delete_request(delete_request_id: int):
    """Fetch a single delete request by id."""
    dr = DeleteRequest.query.get(delete_request_id)
    if not dr:
        return None
    return dr.to_dict()


def list_delete_requests(
    module_code:  str  = None,
    project_code: str  = None,
    status:       str  = None,
    requested_by: int  = None,
    page:         int  = 1,
    per_page:     int  = 20,
) -> dict:
    """List delete requests with optional filters."""
    q = DeleteRequest.query

    if module_code:
        q = q.filter_by(module_code=module_code)
    if project_code:
        q = q.filter_by(project_code=project_code)
    if status:
        q = q.filter_by(status=status)
    if requested_by:
        q = q.filter_by(requested_by=requested_by)

    q = q.order_by(DeleteRequest.requested_at.desc())
    paginated = q.paginate(page=page, per_page=per_page, error_out=False)

    return {
        "total":   paginated.total,
        "page":    page,
        "pages":   paginated.pages,
        "results": [dr.to_dict() for dr in paginated.items],
    }


def cancel_delete_request(delete_request_id: int, cancelled_by: int) -> dict:
    """Cancel a pending delete request."""
    dr = DeleteRequest.query.get(delete_request_id)
    if not dr:
        return {"status": "error", "message": "Delete request not found"}, 404
    if dr.status != "PENDING":
        return {"status": "error", "message": f"Cannot cancel a {dr.status} request"}, 400

    dr.status       = "CANCELLED"
    dr.cancelled_by = cancelled_by
    dr.cancelled_at = datetime.utcnow()
    db.session.commit()

    return {"status": "cancelled", "message": "Delete request cancelled."}, 200


def check_delete_status(module_code: str, record_id: int) -> tuple[dict, int]:
    """
    Frontend helper — call before showing the delete button.
    Returns whether the record can be deleted immediately or is blocked.

    Response shape:
      {
        "can_delete_now": bool,
        "blocked_by": [{"doc_no", "module_code", "label", "record_id"}],
        "pending_request": {delete_request fields} | null,
      }
    """
    config = DEPENDENCY_MAP.get(module_code)
    if not config:
        return {"status": "error", "message": f"Unknown module: {module_code}"}, 400

    model_class = config["model_class"]
    record = model_class.query.get(record_id)
    if not record:
        return {"status": "error", "message": "Record not found"}, 404

    # Check if there is already a PENDING delete request for this record
    existing_dr = DeleteRequest.query.filter_by(
        module_code=module_code,
        record_id=record_id,
        status="PENDING",
    ).first()

    blocking = _check_children(module_code, record_id, config)

    return {
        "can_delete_now":  len(blocking) == 0,
        "blocked_by":      blocking,
        "pending_request": existing_dr.to_dict() if existing_dr else None,
        "module_code":     module_code,
        "record_id":       record_id,
        "record_no":       _get_record_no(record, config),
    }, 200


def list_notifications(
    module_code:  str = None,
    project_code: str = None,
    status:       str = None,
    wa_sent_only: bool = True,
    page:         int = 1,
    per_page:     int = 20,
) -> dict:
    """
    Notification centre — returns delete requests where a WhatsApp alert was sent.
    Each row is enriched with human-readable module name and requester details.
    """
    from app.models.user import User
    from .dependency_map import MODULE_DISPLAY_NAMES

    q = DeleteRequest.query

    if wa_sent_only:
        q = q.filter(DeleteRequest.wa_sent == True)   # noqa: E712
    if module_code:
        q = q.filter_by(module_code=module_code)
    if project_code:
        q = q.filter_by(project_code=project_code)
    if status:
        q = q.filter_by(status=status)

    q = q.order_by(DeleteRequest.wa_sent_at.desc().nullslast(), DeleteRequest.requested_at.desc())
    paginated = q.paginate(page=page, per_page=per_page, error_out=False)

    results = []
    for dr in paginated.items:
        row = dr.to_dict()
        # Enrich with display names
        row["module_display_name"] = MODULE_DISPLAY_NAMES.get(dr.module_code, dr.module_code)
        # Requester name
        requester = User.query.get(dr.requested_by) if dr.requested_by else None
        row["requested_by_name"] = (
            f"{requester.first_name} {requester.last_name}".strip()
            if requester else None
        )
        results.append(row)

    return {
        "total":   paginated.total,
        "page":    page,
        "pages":   paginated.pages,
        "results": results,
    }
