"""
Central Accounting — Document Reversal Service.

The ONE place that takes a posted document out of the books. Ledger rows are
never deleted: the original posting stays, a reversal posting (Dr/Cr swapped)
is added, and the original is flagged is_reversed=True.

Three ways in, one engine:

  1. CANCEL   — POST /finance/accounting/cancel, or the Delete button on a
                posted document (delete manager routes it here).
                Reversal + document marked "Cancelled" (kept, number kept,
                never deleted). Stock reversed, bank line released.
  2. REBACK   — reback request accepted (workflow/unapprove.py).
                Reversal only; document goes back to the creator as Reback.
                Re-approval posts a fresh posting (new active posting).
  3. DELETE   — of a document that is NOT in the books (draft, rejected, or
                rebacked-and-not-re-approved): plain hard delete; any old
                original+reversal pair stays in the ledger as the audit trail.

Safety checks before a cancel (same family as reback):
  * permission  — admin, or the final approver of that module for the project
  * reason      — mandatory
  * downstream  — nothing made from it (payments, receipts, BRG/BRB, …)
  * FY lock     — the posting's financial year must be open
  * stock       — GRN/GIN only while they are the latest movement
"""

from datetime import datetime

from app.extensions import db

from .posting_engine import active_posting, reverse_posting
from .deletion_guard import posting_source_for


class ReversalBlocked(Exception):
    """Cancellation not allowed; message says why. .status is the HTTP code."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ==========================================
# REGISTRY LOOKUPS (reuse workflow/unapprove.UNAPPROVE_MODULES)
# ==========================================

def _U():
    from app.modules.workflow import unapprove
    return unapprove


def key_for_dep(module_code):
    """delete-manager module code (PURCHASE_BILL) → unapprove key (purchase_bill)."""
    for key, entry in _U().UNAPPROVE_MODULES.items():
        if entry.get("dep") == module_code:
            return key
    return None


_SOURCE_ALIASES = {"sale_claim_bill": "project_billing", "sale_certified_bill": "project_billing"}


def key_for_source(source_type):
    """accounting source_type (purchase_bill) → unapprove key."""
    if source_type in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[source_type]
    for key, entry in _U().UNAPPROVE_MODULES.items():
        if entry.get("posting") == source_type:
            return key
    return None


def source_type_for(key, record):
    entry = _U().UNAPPROVE_MODULES.get(key) or {}
    spec = entry.get("posting")
    if spec is None:
        return posting_source_for(record)
    return spec(record) if callable(spec) else spec


def has_active_posting(record, key=None):
    source = source_type_for(key, record) if key else posting_source_for(record)
    return bool(source) and active_posting(source, record.id) is not None


# ==========================================
# CHECKS
# ==========================================

def _is_admin():
    return _U().is_admin()


def can_cancel(key, record, user_id):
    """Admin, or the final approver of this module for the record's project."""
    if _is_admin():
        return True
    from app.modules.workflow.reback_request import final_approvers, _approval_code
    U = _U()
    try:
        project = U._project(U.UNAPPROVE_MODULES[key], record)
        return user_id is not None and user_id in final_approvers(project, _approval_code(key, record))
    except Exception:
        return False


def user_can_cancel(key, record, user_id):
    """can_cancel for a given user id (no request context) — used when a
    pending delete request auto-cancels later on behalf of its requester."""
    from app.models.user import User
    U = _U()
    u = User.query.get(user_id) if user_id else None
    if not u:
        return False
    if u.global_role and u.global_role.name in U.ADMIN_ROLES:
        return True
    from app.modules.workflow.reback_request import final_approvers, _approval_code
    try:
        project = U._project(U.UNAPPROVE_MODULES[key], record)
        return user_id in final_approvers(project, _approval_code(key, record))
    except Exception:
        return False


def cancel_hard_problem(key, record, user_id, check_permission=True):
    """
    Problems a delete REQUEST cannot wait out: not cancellable, already
    cancelled, not posted, no permission, locked FY / later stock movement.
    None, or (message, http_status). Downstream documents are NOT checked
    here — those make the request PENDING (see delete manager).
    """
    U = _U()
    entry = U.UNAPPROVE_MODULES.get(key)
    if not entry:
        return "This document type cannot be cancelled", 400
    if (record.workflow_status or "") == "Cancelled":
        return "Document is already cancelled", 409
    source = source_type_for(key, record)
    if not source or active_posting(source, record.id) is None:
        return "Document is not posted to accounts — nothing to reverse", 400
    if check_permission and not can_cancel(key, record, user_id):
        return "Only the final approver or an admin can cancel a posted document", 403
    reasons = U._check_ledgers(entry, record)
    if reasons:
        return reasons[0], 400
    return None


def cancel_problem(key, record, user_id, check_permission=True):
    """None when the record can be cancelled now, else (message, http_status)."""
    hard = cancel_hard_problem(key, record, user_id, check_permission)
    if hard:
        return hard
    blockers = _U().find_blockers(key, record)
    if blockers:
        shown = ", ".join(blockers[:10]) + (f" and {len(blockers) - 10} more" if len(blockers) > 10 else "")
        return f"Used in {shown}. Cancel or delete those first.", 400
    return None


def extra_blocker_dicts(key, record):
    """
    The registry's EXTRA "used in" links (beyond the delete-manager map) as
    delete-manager blocker dicts — e.g. docket lines in a Bulk Docket, credit
    notes against a sale bill. Cancelled documents never block.
    """
    U = _U()
    entry = U.UNAPPROVE_MODULES.get(key) or {}
    from app.modules.delete_manager.dependency_map import DEPENDENCY_MAP
    out = []
    for path, fk, doc_field, label in entry.get("extra", []):
        model = U._load(path)
        rows = model.query.filter(getattr(model, fk) == record.id).all()
        if label == "Bulk Docket":
            from app.models.journalVoucher import PettyCashJournalVoucher
            ids = {getattr(r, doc_field) for r in rows}
            for jv in (PettyCashJournalVoucher.query.filter(PettyCashJournalVoucher.id.in_(ids)).all() if ids else []):
                out.append({"doc_no": jv.voucher_no or f"#{jv.id}", "module_code": "JOURNAL_VOUCHER",
                            "label": label, "record_id": jv.id})
            continue
        mod = next((c for c, cfg in DEPENDENCY_MAP.items() if cfg["model_class"] is model), label)
        for r in rows:
            if (getattr(r, "workflow_status", None) or "") == "Cancelled":
                continue
            out.append({"doc_no": str(getattr(r, doc_field, None) or r.id), "module_code": mod,
                        "label": label, "record_id": r.id})
    return out


# ==========================================
# ENGINE
# ==========================================

def reverse_for_reback(entry, record, user_id, remarks=None):
    """
    Reback after approval: reverse the active posting (no delete).
    Called from unapprove._apply, which already ran the FY / stock checks.
    Caller commits.
    """
    spec = entry.get("posting")
    source = spec(record) if callable(spec) else spec
    if not source:
        return None
    note = f"Reback: {remarks}" if remarks else None
    return reverse_posting(source, record.id, user_id, remarks=(note or "")[:1000] or None)


def _release_bank_line(record, user_id):
    U = _U()
    U._unreconcile_bank_line(record, user_id)
    from app.modules.finance.bank_statement.service import release_for_docket
    release_for_docket(record, user_id, "Docket cancelled")


def _mark_cancelled(key, record, user_id, reason):
    U = _U()
    entry = U.UNAPPROVE_MODULES[key]
    now = datetime.utcnow()
    level = getattr(record, "current_level", None)
    record.workflow_status = "Cancelled"
    for attr, value in (("locked", True), ("cancelled_by", user_id), ("cancelled_at", now),
                        ("cancellation_reason", reason), ("updated_by", user_id), ("updated_at", now)):
        if hasattr(record, attr):
            setattr(record, attr, value)

    from app.modules.work_flow import create_history
    create_history(
        project_code=U._project(entry, record),
        module_code=U._value(entry["history"], record),
        record_id=record.id,
        level_no=level,
        action="CANCELLED",
        action_by=user_id,
        comments=f"[Cancelled — reversal posted] {reason}",
    )


def cancel_document(key, record_id, user_id, reason, check_permission=True):
    """
    Cancel a posted document: reversal posting + status Cancelled, in ONE
    transaction (all or nothing). Commits.

    Returns (payload_dict, http_status).
    """
    U = _U()
    entry = U.UNAPPROVE_MODULES.get(key)
    if not entry:
        return {"status": "error", "message": "This document type cannot be cancelled"}, 400
    reason = str(reason or "").strip()
    if not reason:
        return {"status": "error", "message": "A reason is required to cancel a posted document"}, 400

    model = U._load(entry["model"])
    try:
        db.session.query(model.id).filter(model.id == record_id).with_for_update().first()
        record = model.query.populate_existing().get(record_id)
        if not record:
            return {"status": "error", "message": "Record not found"}, 404

        problem = cancel_problem(key, record, user_id, check_permission)
        if problem:
            msg, code = problem
            return {"status": "error", "message": msg}, code

        source = source_type_for(key, record)
        reversal = reverse_posting(source, record.id, user_id, remarks=f"Cancelled: {reason}"[:1000])
        if reversal is None:
            raise ReversalBlocked("Document is not posted to accounts — nothing to reverse", 409)

        if entry.get("stock"):
            from .stock_ledger_service import reverse_stock_entry
            reverse_stock_entry(entry["stock"], record.id, user_id)   # errors abort everything
        if entry.get("bank_line"):
            _release_bank_line(record, user_id)

        _mark_cancelled(key, record, user_id, reason)
        doc_no = U._doc_no(entry, record)
        db.session.commit()
    except ReversalBlocked as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, e.status
    except Exception as e:
        db.session.rollback()
        msg = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        code = 400 if type(e).__name__ == "LinkError" else 500   # bank line already reconciled etc.
        return {"status": "error", "message": f"Cancellation failed: {msg}"}, code

    return {
        "status": "cancelled",
        "message": (f"{doc_no} was posted to accounts, so it was cancelled with reversal "
                    f"entry {reversal.voucher_no} instead of being deleted."),
        "reversalId": reversal.id,
        "reversalVoucherNo": reversal.voucher_no,
        "sourceType": source,
        "sourceId": record.id,
        "cancelledBy": user_id,
        "reason": reason,
    }, 200


def assert_hard_deletable(record):
    """
    Last line of defence for any code path that physically deletes a record
    (delete manager, auto-complete, recheck, fix scripts).
    """
    if (getattr(record, "workflow_status", None) or "") == "Cancelled" and posting_source_for(record):
        raise ReversalBlocked("Cancelled documents are kept for audit and cannot be deleted")
    if has_active_posting(record):
        raise ReversalBlocked(
            "Document is posted to the accounting ledger — it must be cancelled "
            "(reversal entry), not deleted")


def posting_history(source_type, source_id):
    """All postings of a document, oldest first (for the cancellation-status API)."""
    from app.models.accounting import AccountingLedger
    rows = AccountingLedger.query.filter_by(source_type=source_type, source_id=source_id) \
        .order_by(AccountingLedger.id).all()
    return [{
        "id": r.id,
        "voucherNo": r.voucher_no,
        "postingDate": r.posting_date.isoformat() if r.posting_date else None,
        "isReversal": bool(r.is_reversal),
        "isReversed": bool(r.is_reversed),
        "reversedPostingId": r.reversed_posting_id,
        "amount": float(r.total_debit or 0),
        "remarks": r.remarks,
        "createdBy": r.created_by,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
