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

from app.utils.pagination import set_pagination
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


def _check_dc_in_logistics_bill(dc_id: int) -> list[dict]:
    """Block DC delete when it has been included in a Logistics Bill."""
    from app.models.logisticsBill import LogisticsBill, LogisticsBillChallan
    blocking = []
    lb_ids = {r.lb_id for r in LogisticsBillChallan.query.filter_by(dc_id=dc_id).all()}
    for lb_id in lb_ids:
        lb = LogisticsBill.query.get(lb_id)
        if lb:
            blocking.append({
                "doc_no":      lb.lb_no,
                "module_code": "LB",
                "label":       "LB (Logistics Bill) — unlink this DC first",
                "record_id":   lb.id,
            })
    return blocking


def _check_lb_posted_to_finance(lb_id: int) -> list[dict]:
    """Block LB delete when voucher_id is set (bill posted to AP)."""
    from app.models.logisticsBill import LogisticsBill
    blocking = []
    lb = LogisticsBill.query.get(lb_id)
    if lb and lb.voucher_id:
        blocking.append({
            "doc_no":      f"Voucher #{lb.voucher_id}" if lb.voucher_id > 0 else "Posted to AP",
            "module_code": "JOURNAL_ENTRY",
            "label":       "Posted to Finance — reverse the voucher first",
            "record_id":   lb.voucher_id,
        })
    return blocking


def _check_jv_linked_journal(jv_id: int) -> list[dict]:
    """Block Bulk Docket delete while a Bulk Docket Journal (JB…) is made from it."""
    from app.models.journalVoucher import PettyCashJournalVoucher
    from app.models.journalEntry import JournalEntryMaster
    jv = PettyCashJournalVoucher.query.get(jv_id)
    if not jv or not jv.linked_journal_id:
        return []
    je = JournalEntryMaster.query.get(jv.linked_journal_id)
    return [{
        "doc_no":      (je.voucher_no if je else None) or f"#{jv.linked_journal_id}",
        "module_code": "JOURNAL_ENTRY",
        "label":       "Bulk Docket Journal",
        "record_id":   jv.linked_journal_id,
    }]


def _check_docket_in_bulk_docket(docket_id: int) -> list[dict]:
    """Block docket delete while any of its lines sits in a Bulk Docket (BV…)."""
    from app.models.journalVoucher import PettyCashJournalVoucher, PettyCashJournalLine
    jv_ids = {r.journal_voucher_id for r in
              PettyCashJournalLine.query.filter_by(docket_voucher_id=docket_id).all()}
    blocking = []
    for jv in PettyCashJournalVoucher.query.filter(PettyCashJournalVoucher.id.in_(jv_ids)).all() if jv_ids else []:
        blocking.append({
            "doc_no":      jv.voucher_no or f"#{jv.id}",
            "module_code": "JOURNAL_VOUCHER",
            "label":       "Bulk Docket",
            "record_id":   jv.id,
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
        elif check_name == "dc_in_logistics_bill":
            blocking.extend(_check_dc_in_logistics_bill(record_id))
        elif check_name == "lb_posted_to_finance":
            blocking.extend(_check_lb_posted_to_finance(record_id))
        elif check_name == "jv_linked_journal":
            blocking.extend(_check_jv_linked_journal(record_id))
        elif check_name == "docket_in_bulk_docket":
            blocking.extend(_check_docket_in_bulk_docket(record_id))
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
        # Central accounting safety net: a document that is in the books is
        # never hard-deleted (covers raise / auto-complete / recheck / scripts).
        from app.modules.finance.accounting.reversal_service import assert_hard_deletable
        assert_hard_deletable(record)
        try:
            # Rows that only point at the record: clear the pointer, keep the row
            # (config "release_first": [(Model, fk_column)]) — same transaction.
            for ref_model, fk_col in config.get("release_first", []):
                ref_model.query.filter(
                    getattr(ref_model, fk_col) == record_id
                ).update({fk_col: None}, synchronize_session=False)
            # Owned rows the ORM doesn't cascade (config "delete_first": [(Model, fk_column)])
            for owned_model, fk_col in config.get("delete_first", []):
                owned_model.query.filter(
                    getattr(owned_model, fk_col) == record_id
                ).delete(synchronize_session=False)
            db.session.delete(record)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def _accounting_route(module_code: str, record):
    """
    How the delete button must treat this record, as far as accounting goes:
      "delete" — not in the books: normal delete flow
      "cancel" — has an active posting: cancel with a reversal entry instead
      "kept"   — already Cancelled (posted earlier): never deleted
      "refuse" — posted, but the module has no cancellation support
    """
    from app.modules.finance.accounting.reversal_service import (
        has_active_posting, key_for_dep, source_type_for,
    )
    from app.modules.finance.accounting.deletion_guard import posting_source_for, was_ever_posted
    key = key_for_dep(module_code)
    source = source_type_for(key, record) if key else posting_source_for(record)
    if not source:
        return "delete"
    if (getattr(record, "workflow_status", None) or "") == "Cancelled" and was_ever_posted(source, record.id):
        return "kept"
    if has_active_posting(record, key):
        return "cancel" if key else "refuse"
    return "delete"


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

    access_check = config.get("access_check")
    if access_check and not access_check(record, requested_by):
        return {"status": "error", "message": "You do not have permission to delete this record"}, 403

    # ── Central accounting: posted documents are cancelled, not deleted ──
    accounting = _accounting_route(module_code, record)
    if accounting == "kept":
        return {"status": "error",
                "message": "Cancelled documents are kept for audit and cannot be deleted."}, 400
    if accounting == "cancel":
        from app.modules.finance.accounting.reversal_service import cancel_document, key_for_dep
        return cancel_document(key_for_dep(module_code), record_id, requested_by, reason)
    if accounting == "refuse":
        return {"status": "error",
                "message": "This document is posted to the accounting ledger and cannot be deleted."}, 400

    record_no    = _get_record_no(record, config)
    project_code = _get_project_code(record, config)
    display_name = get_display_name(module_code)

    # Check if a PENDING delete request already exists for this record
    existing = DeleteRequest.query.filter_by(
        module_code=module_code,
        record_id=record_id,
        status="PENDING",
    ).first()

    # Find blocking children
    blocking = _check_children(module_code, record_id, config)

    if existing and blocking:
        # Still blocked — return current status
        return {
            "status":            "pending",
            "delete_request_id": existing.id,
            "message":           f"A delete request for {display_name} {record_no} is already pending.",
            "blocked_by":        json.loads(existing.blocked_by_modules or "[]"),
        }, 200

    if not blocking:
        # No downstream records — delete immediately
        _do_delete_record(module_code, record_id, config)
        # If there was a PENDING request for this record, mark it COMPLETED now
        if existing:
            existing.status       = "COMPLETED"
            existing.completed_at = datetime.utcnow()
            db.session.commit()
        # Notify requester via WA that delete is done
        from app.models.user import User
        requester = User.query.get(requested_by)
        notify_delete_completed(
            module_code=module_code,
            record_no=record_no,
            project_code=project_code,
            requester_user=requester,
        )
        # Trigger cascade: any parent records waiting for this child to be deleted
        auto_complete_check(module_code, record_id)
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
        # Refresh in case a cascading auto_complete_check already processed this DR
        db.session.refresh(dr)
        if dr.status != "PENDING":
            continue

        # Re-evaluate blocking children for this parent record
        config = DEPENDENCY_MAP.get(dr.module_code)
        if not config:
            continue

        current_blocking = _check_children(dr.module_code, dr.record_id, config)

        if not current_blocking:
            # All blockers gone — perform the actual delete now
            deleted_module = dr.module_code
            deleted_id     = dr.record_id
            try:
                _do_delete_record(dr.module_code, dr.record_id, config)
            except Exception as e:
                # Delete refused (e.g. posted to accounts) or failed — the
                # request stays PENDING with the reason; never mark COMPLETED.
                db.session.rollback()
                dr.blocked_by_docs = str(e).splitlines()[0][:250] if str(e) else type(e).__name__
                db.session.commit()
                continue

            dr.status             = "COMPLETED"
            dr.completed_at       = datetime.utcnow()
            dr.blocked_by_modules = "[]"
            dr.blocked_by_docs    = ""
            db.session.commit()

            from app.models.user import User
            requester = User.query.get(dr.requested_by)
            notify_delete_completed(
                module_code    = dr.module_code,
                record_no      = dr.record_no,
                project_code   = dr.project_code,
                requester_user = requester,
            )

            # Cascade: deleting this record may unblock further pending DRs
            auto_complete_check(deleted_module, deleted_id)
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
    set_pagination(paginated.total, page, per_page)  # standard top-level "pagination"

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

    # Central accounting: a posted document is cancelled (reversal), not deleted
    accounting = _accounting_route(module_code, record)
    cancel_problem = None
    if accounting == "cancel":
        from flask import g
        from app.modules.finance.accounting.reversal_service import (
            cancel_problem as _cancel_problem, key_for_dep,
        )
        user_id = (g.get("current_user") or {}).get("id")
        problem = _cancel_problem(key_for_dep(module_code), record, user_id)
        cancel_problem = problem[0] if problem else None
    elif accounting in ("kept", "refuse"):
        cancel_problem = ("Cancelled documents are kept for audit and cannot be deleted."
                          if accounting == "kept" else
                          "This document is posted to the accounting ledger and cannot be deleted.")

    return {
        "can_delete_now":  len(blocking) == 0 and cancel_problem is None,
        "blocked_by":      blocking,
        "pending_request": existing_dr.to_dict() if existing_dr else None,
        "module_code":     module_code,
        "record_id":       record_id,
        "record_no":       _get_record_no(record, config),
        # "delete" | "cancel" (posted → reversal entry) | "kept" | "refuse"
        "accounting_action": accounting,
        "will_cancel":     accounting == "cancel",
        "cancel_problem":  cancel_problem,
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
    set_pagination(paginated.total, page, per_page)  # standard top-level "pagination"

    results = []
    for dr in paginated.items:
        row = dr.to_dict()
        # Enrich with display names
        row["module_display_name"] = MODULE_DISPLAY_NAMES.get(dr.module_code, dr.module_code)
        # Requester name
        requester = User.query.get(dr.requested_by) if dr.requested_by else None
        row["requested_by_name"] = (
            requester.username
            if requester else None
        )
        results.append(row)

    return {
        "total":   paginated.total,
        "page":    page,
        "pages":   paginated.pages,
        "results": results,
    }
