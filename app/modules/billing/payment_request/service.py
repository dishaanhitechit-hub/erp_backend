"""
Payment Request — raised against an Approved BRR (Bill Receive Register)
or an Approved Journal Entry.

Rules
─────
* Source BRR: only an Approved BRR. Bill amount = total of the BRR's Approved
  BRB when one exists, else BRR total.
* Source JOURNAL: only an Approved journal entry (any entry mode). One request
  covers ONE vendor of that journal — another vendor of the same journal gets
  its own request (own PR No). Bill amount = that vendor's Cr lines total.
* Partial requests are allowed per source (BRR, or journal + vendor) as long
  as the sum of requested amounts of all non-Rejected requests never exceeds
  the bill amount. The balance is re-validated (source row locked) on create,
  edit, submit and final approval.
* Creator / approver checks follow the approval path of the source:
  BRR requests → module `payment_request`, journal requests → module
  `payment_request_journal` (its own creators and approvers).
* Journal-sourced requests are restricted: only users holding the
  `payment_request_journal` page permission (granted by super admin in
  Settings › Roles & User Assignment) can see them — VIEW to see / approve,
  EDIT to raise / edit / submit / delete. Approvers need it too.
* Source ADVANCE: money asked for a vendor before any bill exists. Only a
  vendor (sundry creditor of the project) is chosen — no bill ceiling. It
  follows the BRR approval path (`payment_request`). Once Approved it is paid
  from Account › Payment (payment type "advance"), in one or more parts.
  Later the advance is LINKED to an Approved BRR or journal of the same vendor
  (link_type). From then on it counts in that source's requested total, the
  same way a BRR / journal request does, and its approved payments reduce the
  balance of the bill in Account › Payment.
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime
import time as _time
import uuid as _uuid_lib

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster
from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.paymentRequest import PaymentRequestMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.project import Project
from app.models.vendor import Vendor
from app.models.user import User
from app.response import res
from app.utils.date_utils import parse_date
from app.cloudinary_uploader import upload_file_to_bunny, delete_file_from_storage
from app.modules.communication import whatsapp_events as wa
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    get_gap_level,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

_MODULE_BRR     = "payment_request"          # approval path / page code (BRR requests)
_MODULE_JOURNAL = "payment_request_journal"  # approval path / page code (journal requests)
_WA_CODE  = "payment_request"          # whatsapp module code
_JOURNAL_PERM = "payment_request_journal"  # restricted page permission
_NO_BASE  = 930000                     # PR serial range (BRR 900000, BRB 910000, BRS 920000)
_TWO_DP   = Decimal("0.01")
_PAYMENT_MODES = {"Bank", "Cash"}

SRC_BRR     = "BRR"
SRC_JOURNAL = "JOURNAL"
SRC_ADVANCE = "ADVANCE"
_SOURCES    = (SRC_BRR, SRC_JOURNAL, SRC_ADVANCE)
_DEAD       = ("Rejected", "Cancelled")   # statuses that free a balance


def _wf(pr_or_source):
    """Approval-path module code for a request (or a source type string).
    ADVANCE requests use the BRR path."""
    src = pr_or_source if isinstance(pr_or_source, str) else (pr_or_source.source_type or SRC_BRR)
    return _MODULE_JOURNAL if src == SRC_JOURNAL else _MODULE_BRR


class _Forbidden(Exception):
    """Raised when the user lacks the journal payment-request permission."""


# ══════════════════════════════════════════════════════════════════
# HELPERS — generic
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    try:
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d %H:%M")
        return d.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def _dec(value, field):
    """Parse a money value into a 2-dp Decimal; blank → 0."""
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(_TWO_DP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a valid number")


def _q(v):
    return Decimal(str(v or 0)).quantize(_TWO_DP)


def _f(v):
    return float(v or 0)


def _rollback_res(e, code):
    db.session.rollback()
    return res(str(e), [], code)


def generate_pr_no():
    last = (
        db.session.query(PaymentRequestMaster.pr_no)
        .order_by(PaymentRequestMaster.id.desc())
        .with_for_update()
        .first()
    )
    try:
        last_serial = int(last[0]) if last else _NO_BASE
    except Exception:
        last_serial = _NO_BASE
    return str(last_serial + 1)


def _sum_requested(filters, exclude_id=None, status=None):
    q = db.session.query(func.coalesce(func.sum(PaymentRequestMaster.requested_amount), 0)).filter(*filters)
    if status:
        q = q.filter(PaymentRequestMaster.workflow_status == status)
    else:
        q = q.filter(PaymentRequestMaster.workflow_status.notin_(("Rejected", "Cancelled")))
    if exclude_id:
        q = q.filter(PaymentRequestMaster.id != exclude_id)
    return _q(q.scalar())


def _check_amounts(label, bill, previous, requested, deduction):
    if requested <= 0:
        raise ValueError("Requested amount must be greater than 0")
    if deduction < 0:
        raise ValueError("Deduction amount cannot be negative")
    if deduction > requested:
        raise ValueError("Deduction amount cannot exceed requested amount")
    balance = bill - previous
    if requested > balance:
        raise ValueError(
            f"Requested amount {requested} exceeds {label} balance {balance} "
            f"(bill {bill}, already requested {previous})"
        )


# ══════════════════════════════════════════════════════════════════
# HELPERS — journal permission (restricted visibility)
# ══════════════════════════════════════════════════════════════════

def _is_super_admin(user_id):
    try:
        user = User.query.get(int(user_id)) if user_id else None
    except (TypeError, ValueError):
        return False
    return bool(user and user.global_role and user.global_role.name == "super_admin")


def has_journal_permission(project_code, user_id, action="VIEW"):
    """True if the user holds payment_request_journal.<action> in this project.
    EDIT implies VIEW. Super admin always allowed."""
    if not user_id:
        return False
    if _is_super_admin(user_id):
        return True
    project = Project.query.filter_by(project_code=project_code).first() if project_code else None
    if not project:
        return False
    from app.modules.setting.permission_service import get_user_permissions
    try:
        perms = get_user_permissions(project.id, int(user_id)) or {}
    except Exception:
        db.session.rollback()
        return False
    if perms.get(f"{_JOURNAL_PERM}.EDIT"):
        return True
    return action == "VIEW" and bool(perms.get(f"{_JOURNAL_PERM}.VIEW"))


def _require_journal(project_code, user_id, action):
    if not has_journal_permission(project_code, user_id, action):
        raise _Forbidden("You do not have permission for journal payment requests")


def _guard(pr, user_id, action="VIEW"):
    """Journal-sourced requests need the journal permission; BRR ones don't."""
    if pr.source_type == SRC_JOURNAL:
        _require_journal(pr.project_code, user_id, action)


def can_view_record(pr, user_id):
    """Used by workflow my-approvals to hide journal requests from others."""
    return pr.source_type != SRC_JOURNAL or has_journal_permission(pr.project_code, user_id, "VIEW")


# ══════════════════════════════════════════════════════════════════
# HELPERS — BRR source
# ══════════════════════════════════════════════════════════════════

def _lock_brr(brr_id):
    return BrrMaster.query.filter(BrrMaster.id == brr_id).with_for_update().first()


def _approved_brb(brr_id):
    return (
        BrbMaster.query
        .filter(BrbMaster.brr_id == brr_id, BrbMaster.workflow_status == "Approved")
        .order_by(BrbMaster.id.desc())
        .first()
    )


def _linked_brb(brr_id):
    """The BRR's billing record (BRB) shown to the user: latest non-Rejected one."""
    return (
        BrbMaster.query
        .filter(BrbMaster.brr_id == brr_id, BrbMaster.workflow_status.notin_(("Rejected", "Cancelled")))
        .order_by(BrbMaster.id.desc())
        .first()
    )


def _brr_bill_amount(brr):
    """Approved BRB total when present (actual reconciled bill), else BRR total."""
    brb = _approved_brb(brr.id)
    return _q(brb.total_amount if brb else brr.total_amount)


def _brr_filters(brr_id):
    """BRR requests + advances linked to this BRR."""
    return [PaymentRequestMaster.source_type.in_((SRC_BRR, SRC_ADVANCE)), PaymentRequestMaster.brr_id == brr_id]


def _brr_summary(brr, exclude_id=None):
    bill      = _brr_bill_amount(brr)
    requested = _sum_requested(_brr_filters(brr.id), exclude_id)
    brb       = _linked_brb(brr.id)
    return {
        "sourceType":      SRC_BRR,
        "brrId":           brr.id,
        "brrNo":           brr.brr_no,
        "brrDate":         _fmt_date(brr.brr_date),
        "brrStatus":       brr.workflow_status,
        "vendorId":        brr.vendor_id,
        "partyName":       brr.vendor.ledger_name if brr.vendor else None,
        "orderCategory":   brr.order_category,
        "orderNo":         (brr.order.order_no if brr.order_type == "GRN" and brr.order
                            else brr.pw_order.order_no if brr.pw_order else None),
        "partyBillNo":     brr.party_bill_no,
        "partyDate":       _fmt_date(brr.party_date),
        "brbId":           brb.id if brb else None,
        "brbNo":           brb.brb_no if brb else None,
        "brbStatus":       brb.workflow_status if brb else None,
        "brrTotalAmount":  _f(brr.total_amount),
        "billAmount":      float(bill),
        "billSource":      "BRB" if _approved_brb(brr.id) else "BRR",
        "requestedAmount": float(requested),   # other active requests
        "approvedAmount":  float(_sum_requested(_brr_filters(brr.id), exclude_id, status="Approved")),
        "balanceAmount":   float(bill - requested),
    }


def _validate_brr(brr, requested, deduction, exclude_id=None):
    if brr.workflow_status != "Approved":
        raise ValueError(f"BRR {brr.brr_no} is not Approved")
    bill     = _brr_bill_amount(brr)
    previous = _sum_requested(_brr_filters(brr.id), exclude_id)
    _check_amounts(f"BRR {brr.brr_no}", bill, previous, requested, deduction)
    return bill, previous


# ══════════════════════════════════════════════════════════════════
# HELPERS — JOURNAL source (one vendor per request)
# ══════════════════════════════════════════════════════════════════

def _lock_journal(journal_id):
    return JournalEntryMaster.query.filter(JournalEntryMaster.id == journal_id).with_for_update().first()


def _journal_vendor_bill(journal_id, vendor_id):
    """Total of the vendor's Cr lines in the journal (amount payable to vendor)."""
    total = (
        db.session.query(func.coalesce(func.sum(JournalEntryLine.credit_amount), 0))
        .filter(
            JournalEntryLine.journal_id == journal_id,
            JournalEntryLine.dr_cr      == "Cr",
            JournalEntryLine.vendor_id  == vendor_id,
        )
        .scalar()
    )
    return _q(total)


def _journal_filters(journal_id, vendor_id):
    """Journal requests + advances linked to this journal, for one vendor."""
    return [
        PaymentRequestMaster.source_type.in_((SRC_JOURNAL, SRC_ADVANCE)),
        PaymentRequestMaster.journal_id  == journal_id,
        PaymentRequestMaster.vendor_id   == vendor_id,
    ]


def _journal_summary(je, vendor_id, exclude_id=None):
    vendor    = Vendor.query.get(vendor_id) if vendor_id else None
    bill      = _journal_vendor_bill(je.id, vendor_id)
    filters   = _journal_filters(je.id, vendor_id)
    requested = _sum_requested(filters, exclude_id)
    return {
        "sourceType":      SRC_JOURNAL,
        "journalId":       je.id,
        "voucherNo":       je.voucher_no,
        "entryDate":       _fmt_date(je.entry_date),
        "entryMode":       je.entry_mode,
        "journalStatus":   je.workflow_status,
        "journalRemarks":  je.remarks,
        "vendorId":        vendor_id,
        "partyName":       vendor.ledger_name if vendor else None,
        "billAmount":      float(bill),
        "billSource":      "JOURNAL",
        "requestedAmount": float(requested),   # other active requests for this journal + vendor
        "approvedAmount":  float(_sum_requested(filters, exclude_id, status="Approved")),
        "balanceAmount":   float(bill - requested),
    }


def _validate_journal(je, vendor_id, requested, deduction, exclude_id=None):
    if je.workflow_status != "Approved":
        raise ValueError(f"Journal {je.voucher_no} is not Approved")
    bill = _journal_vendor_bill(je.id, vendor_id)
    if bill <= 0:
        raise ValueError(f"Selected vendor has no Cr entry in journal {je.voucher_no}")
    previous = _sum_requested(_journal_filters(je.id, vendor_id), exclude_id)
    _check_amounts(f"Journal {je.voucher_no}", bill, previous, requested, deduction)
    return bill, previous


# ══════════════════════════════════════════════════════════════════
# HELPERS — ADVANCE source (vendor only; linked to BRR / journal later)
# ══════════════════════════════════════════════════════════════════

def _project_vendor_ids(project_code):
    """Sundry creditors connected with the project: linked to it in the vendor
    master, or already used on one of its orders / BRRs / purchase bills /
    journal Cr lines."""
    from app.models.vendor import VendorProject
    from app.models.orderMaster import OrderMaster
    from app.models.purchaseBill import PurchaseBillMaster

    ids = set()
    project = Project.query.filter_by(project_code=project_code).first()
    if project:
        ids |= {r[0] for r in db.session.query(VendorProject.vendor_id)
                .filter(VendorProject.project_id == project.id).all()}
    for model in (OrderMaster, BrrMaster, PurchaseBillMaster):
        ids |= {r[0] for r in db.session.query(model.vendor_id)
                .filter(model.project_code == project_code, model.vendor_id.isnot(None)).distinct().all()}
    ids |= {r[0] for r in db.session.query(JournalEntryLine.vendor_id)
            .join(JournalEntryMaster, JournalEntryLine.journal_id == JournalEntryMaster.id)
            .filter(JournalEntryMaster.project_code == project_code,
                    JournalEntryLine.dr_cr == "Cr",
                    JournalEntryLine.vendor_id.isnot(None)).distinct().all()}
    return ids


def _project_creditors(project_code):
    ids = _project_vendor_ids(project_code)
    if not ids:
        return []
    return (
        Vendor.query
        .filter(Vendor.id.in_(ids), Vendor.is_debtor.isnot(True))
        .order_by(Vendor.ledger_name.asc())
        .all()
    )


def _validate_advance(project_code, vendor_id, requested, deduction):
    vendor = Vendor.query.get(vendor_id) if vendor_id else None
    if not vendor:
        raise ValueError("Vendor not found")
    if vendor.is_debtor:
        raise ValueError("Advance can be raised only for a sundry creditor")
    if vendor.id not in _project_vendor_ids(project_code):
        raise ValueError(f"{vendor.ledger_name} is not connected with this project")
    # no bill yet → no ceiling; only the amount rules apply
    _check_amounts("advance", requested, Decimal("0.00"), requested, deduction)
    return vendor


def advance_paid(pr_id, exclude_receipt_id=None):
    """(approved, in_progress) amounts paid from Account › Payment against an
    ADVANCE request. Rejected / Cancelled payments are ignored."""
    q = db.session.query(
        BillPaymentReceiptMaster.workflow_status,
        func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0),
    ).filter(
        BillPaymentReceiptMaster.payment_type       == "advance",
        BillPaymentReceiptMaster.payment_request_id == pr_id,
        BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
    )
    if exclude_receipt_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_receipt_id)
    approved = in_progress = Decimal("0.00")
    for status, amt in q.group_by(BillPaymentReceiptMaster.workflow_status).all():
        if status == "Approved":
            approved += _q(amt)
        else:
            in_progress += _q(amt)
    return approved, in_progress


def _advance_payments(pr):
    rows = (
        BillPaymentReceiptMaster.query
        .filter(BillPaymentReceiptMaster.payment_type == "advance",
                BillPaymentReceiptMaster.payment_request_id == pr.id)
        .order_by(BillPaymentReceiptMaster.id.asc())
        .all()
    )
    return [
        {
            "id":             r.id,
            "receiptNo":      r.receipt_no,
            "paymentDate":    _fmt_date(r.payment_date),
            "paymentMode":    r.payment_mode,
            "utrVoucherNo":   r.utr_voucher_no,
            "amount":         _f(r.total_invoice_amount),
            "workflowStatus": r.workflow_status,
        }
        for r in rows
    ]


def _advance_summary(pr):
    approved, in_progress = advance_paid(pr.id)
    net = _q(pr.net_payable)
    return {
        "sourceType":        SRC_ADVANCE,
        "vendorId":          pr.vendor_id,
        "partyName":         pr.vendor.ledger_name if pr.vendor else None,
        "netPayable":        float(net),
        "paidAmount":        float(approved),
        "inProgressAmount":  float(in_progress),
        "balanceToPay":      float(max(net - approved - in_progress, Decimal("0.00"))),
    }


def _is_linked(pr):
    return pr.source_type == SRC_ADVANCE and bool(pr.link_type)


def _linked_no(pr):
    if pr.link_type == SRC_JOURNAL:
        return pr.journal_voucher_no
    if pr.link_type == SRC_BRR:
        return pr.brr_no
    return None


# ══════════════════════════════════════════════════════════════════
# HELPERS — dispatch by source
# ══════════════════════════════════════════════════════════════════

def _effective_source(pr):
    """Where the balance lives: BRR / JOURNAL, a linked advance's link_type,
    or ADVANCE (unlinked — no bill)."""
    if pr.source_type == SRC_ADVANCE:
        return pr.link_type or SRC_ADVANCE
    return pr.source_type or SRC_BRR


def _revalidate(pr, requested=None, deduction=None):
    """Lock the source row and re-check this request against its balance.
    Returns (bill, previous)."""
    requested = _q(pr.requested_amount) if requested is None else requested
    deduction = _q(pr.deduction_amount) if deduction is None else deduction
    src = _effective_source(pr)
    if src == SRC_ADVANCE:
        _check_amounts("advance", requested, Decimal("0.00"), requested, deduction)
        return Decimal("0.00"), Decimal("0.00")
    if src == SRC_JOURNAL:
        je = _lock_journal(pr.journal_id)
        if not je:
            raise ValueError("Journal entry not found")
        return _validate_journal(je, pr.vendor_id, requested, deduction, exclude_id=pr.id)
    brr = _lock_brr(pr.brr_id)
    if not brr:
        raise ValueError("BRR not found")
    return _validate_brr(brr, requested, deduction, exclude_id=pr.id)


def _source_summary(pr):
    src = _effective_source(pr)
    if src == SRC_ADVANCE:
        return _advance_summary(pr)
    if src == SRC_JOURNAL:
        return _journal_summary(pr.journal, pr.vendor_id, exclude_id=pr.id) if pr.journal else None
    return _brr_summary(pr.brr, exclude_id=pr.id) if pr.brr else None


def _source_filters(pr):
    src = _effective_source(pr)
    if src == SRC_ADVANCE:
        return None
    if src == SRC_JOURNAL:
        return _journal_filters(pr.journal_id, pr.vendor_id)
    return _brr_filters(pr.brr_id)


def _payload(pr, with_summary=True):
    data = {
        "id":                  pr.id,
        "uuid":                pr.pr_uuid,
        "prNo":                pr.pr_no,
        "prDate":              _fmt_date(pr.pr_date),
        "projectCode":         pr.project_code,
        "sourceType":          pr.source_type or SRC_BRR,
        "brrId":               pr.brr_id,
        "brrNo":               pr.brr_no,
        "journalId":           pr.journal_id,
        "journalVoucherNo":    pr.journal_voucher_no,
        "journalDate":         _fmt_date(pr.journal_date),
        "sourceNo":            (_linked_no(pr) if pr.source_type == SRC_ADVANCE
                                else pr.journal_voucher_no if pr.source_type == SRC_JOURNAL else pr.brr_no),
        "isAdvance":           pr.source_type == SRC_ADVANCE,
        "linkType":            pr.link_type,
        "linkedNo":            _linked_no(pr),
        "linkedAt":            _fmt_date(pr.linked_at),
        "linkedBy":            pr.linker.username if pr.linker else None,
        "vendorId":            pr.vendor_id,
        "partyName":           pr.vendor.ledger_name if pr.vendor else None,
        "orderCategory":       pr.order_category,
        "partyBillNo":         pr.party_bill_no,
        "partyDate":           _fmt_date(pr.party_date),
        "billAmount":          _f(pr.bill_amount),
        "previouslyRequested": _f(pr.previously_requested),
        "requestedAmount":     _f(pr.requested_amount),
        "deductionAmount":     _f(pr.deduction_amount),
        "deductionRemarks":    pr.deduction_remarks,
        "netPayable":          _f(pr.net_payable),
        "paymentMode":         pr.payment_mode,
        "requiredByDate":      _fmt_date(pr.required_by_date),
        "remarks":             pr.remarks,
        "attachedDoc":         pr.attached_doc,
        "workflowStatus":      pr.workflow_status,
        "currentLevel":        pr.current_level,
        "locked":              pr.locked,
        "createdBy":           pr.creator.username  if pr.creator  else None,
        "createdAt":           _fmt_date(pr.created_at),
        "approvedBy":          pr.approver.username if pr.approver else None,
        "finalApprovedAt":     _fmt_date(pr.final_approved_at),
    }
    if pr.source_type == SRC_ADVANCE:
        approved, in_progress = advance_paid(pr.id)
        data["advancePaid"]       = float(approved)
        data["advanceInProgress"] = float(in_progress)
        data["advanceBalance"]    = float(max(_q(pr.net_payable) - approved - in_progress, Decimal("0.00")))
    if with_summary:
        summary = _source_summary(pr)
        filters = _source_filters(pr)
        # keep the old key for BRR so existing UI keeps working
        data["sourceSummary"] = summary
        data["brrSummary"]    = summary if _effective_source(pr) == SRC_BRR else None
        if pr.source_type == SRC_ADVANCE:
            data["advanceSummary"]  = _advance_summary(pr)
            data["advancePayments"] = _advance_payments(pr)
        data["siblingRequests"] = [] if filters is None else [
            {
                "id":              s.id,
                "prNo":            s.pr_no,
                "prDate":          _fmt_date(s.pr_date),
                "sourceType":      s.source_type,
                "requestedAmount": _f(s.requested_amount),
                "netPayable":      _f(s.net_payable),
                "workflowStatus":  s.workflow_status,
            }
            for s in (
                PaymentRequestMaster.query
                .filter(*filters, PaymentRequestMaster.id != pr.id)
                .order_by(PaymentRequestMaster.id.asc())
                .all()
            )
        ]
    return data


def _apply_common_fields(pr, data):
    """Fields shared by create and edit (only keys present in data are applied)."""
    if "paymentMode" in data:
        mode = (data.get("paymentMode") or "").strip() or None
        if mode and mode not in _PAYMENT_MODES:
            raise ValueError("paymentMode must be Bank or Cash")
        pr.payment_mode = mode
    if "requiredByDate" in data:
        pr.required_by_date = parse_date(data.get("requiredByDate"), "requiredByDate")
    if "remarks" in data:
        pr.remarks = data.get("remarks") or None
    if "deductionRemarks" in data:
        pr.deduction_remarks = data.get("deductionRemarks") or None


# ══════════════════════════════════════════════════════════════════
# 1. ELIGIBLE SOURCES
# ══════════════════════════════════════════════════════════════════

def get_eligible_brrs(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BrrMaster.query.filter(
            BrrMaster.project_code    == project_code,
            BrrMaster.workflow_status == "Approved",
        )
        if data.get("vendorId"):
            query = query.filter(BrrMaster.vendor_id == data.get("vendorId"))

        result = []
        for brr in query.order_by(BrrMaster.id.desc()).all():
            summary = _brr_summary(brr)
            if summary["balanceAmount"] > 0:
                result.append(summary)

        return res("Eligible BRRs fetched", result, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def get_brr_payment_summary(brr_id, exclude_id=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)
        return res("BRR payment summary", _brr_summary(brr, exclude_id), 200)
    except Exception as e:
        return _rollback_res(e, 500)


def get_eligible_journals(data, user_id):
    """Approved journals (any mode) — one row per journal + Cr vendor with balance > 0."""
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)
        _require_journal(project_code, user_id, "EDIT")

        query = (
            db.session.query(JournalEntryMaster, JournalEntryLine.vendor_id)
            .join(JournalEntryLine, JournalEntryLine.journal_id == JournalEntryMaster.id)
            .filter(
                JournalEntryMaster.project_code    == project_code,
                JournalEntryMaster.workflow_status == "Approved",
                JournalEntryLine.dr_cr             == "Cr",
                JournalEntryLine.vendor_id.isnot(None),
            )
        )
        if data.get("vendorId"):
            query = query.filter(JournalEntryLine.vendor_id == int(data.get("vendorId")))

        rows = query.distinct().order_by(JournalEntryMaster.id.desc()).all()

        result = []
        for je, vendor_id in rows:
            summary = _journal_summary(je, vendor_id)
            if summary["balanceAmount"] > 0:
                result.append(summary)

        return res("Eligible journals fetched", result, 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def get_journal_payment_summary(journal_id, vendor_id, user_id, exclude_id=None):
    try:
        je = JournalEntryMaster.query.get(journal_id)
        if not je:
            return res("Journal entry not found", [], 404)
        _require_journal(je.project_code, user_id, "VIEW")
        if not vendor_id:
            return res("vendorId required", [], 400)
        return res("Journal payment summary", _journal_summary(je, int(vendor_id), exclude_id), 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE
# ══════════════════════════════════════════════════════════════════

def create_payment_request(data, user_id, files=None):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        source_type = (data.get("sourceType") or SRC_BRR).upper()
        if source_type not in _SOURCES:
            return res("sourceType must be BRR, JOURNAL or ADVANCE", [], 400)

        if source_type == SRC_JOURNAL:
            _require_journal(project_code, user_id, "EDIT")

        if not is_creator(project_code, _wf(source_type), user_id):
            return res("You are not Payment Request creator", [], 403)

        requested = _dec(data.get("requestedAmount"), "requestedAmount")
        deduction = _dec(data.get("deductionAmount"), "deductionAmount")

        pr = PaymentRequestMaster(
            pr_date          = datetime.utcnow().date(),
            pr_uuid          = str(_uuid_lib.uuid4()),
            project_code     = project_code,
            source_type      = source_type,
            requested_amount = requested,
            deduction_amount = deduction,
            net_payable      = requested - deduction,
            workflow_status  = "Draft",
            status           = "Active",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )

        if source_type == SRC_BRR:
            brr_id = data.get("brrId")
            if not brr_id:
                return res("brrId required", [], 400)
            brr = _lock_brr(brr_id)
            if not brr:
                return res("BRR not found", [], 404)
            if brr.project_code != project_code:
                return res("BRR does not belong to this project", [], 400)
            bill, previous = _validate_brr(brr, requested, deduction)
            pr.brr_id         = brr.id
            pr.brr_no         = brr.brr_no
            pr.vendor_id      = brr.vendor_id
            pr.order_category = brr.order_category
            pr.party_bill_no  = brr.party_bill_no
            pr.party_date     = brr.party_date
        elif source_type == SRC_ADVANCE:
            vendor_id = data.get("vendorId")
            if not vendor_id:
                return res("vendorId required", [], 400)
            vendor = _validate_advance(project_code, int(vendor_id), requested, deduction)
            pr.vendor_id = vendor.id
            bill, previous = Decimal("0.00"), Decimal("0.00")
        else:
            journal_id = data.get("journalId")
            vendor_id  = data.get("vendorId")
            if not journal_id:
                return res("journalId required", [], 400)
            if not vendor_id:
                return res("vendorId required", [], 400)
            je = _lock_journal(journal_id)
            if not je:
                return res("Journal entry not found", [], 404)
            if je.project_code != project_code:
                return res("Journal entry does not belong to this project", [], 400)
            bill, previous = _validate_journal(je, int(vendor_id), requested, deduction)
            pr.journal_id         = je.id
            pr.journal_voucher_no = je.voucher_no
            pr.journal_date       = je.entry_date
            pr.vendor_id          = int(vendor_id)

        pr.bill_amount          = bill
        pr.previously_requested = previous
        _apply_common_fields(pr, data)

        pr.pr_no = generate_pr_no()

        doc_file = files.get("attachedDoc") if files else None
        if doc_file:
            pr.attached_doc = upload_file_to_bunny(
                file       = doc_file,
                mainFolder = "payment_request",
                subFolder  = pr.pr_no,
                fileName   = "attached_doc",
            )

        db.session.add(pr)
        db.session.commit()

        return res(
            "Payment Request created",
            {"id": pr.id, "prNo": pr.pr_no, "attachedDoc": pr.attached_doc},
            201,
        )

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST  (journal rows only for permitted users)
# ══════════════════════════════════════════════════════════════════

def get_payment_request_list(data, user_id=None):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PaymentRequestMaster.query.filter(PaymentRequestMaster.project_code == project_code)

        if not has_journal_permission(project_code, user_id, "VIEW"):
            query = query.filter(PaymentRequestMaster.source_type != SRC_JOURNAL)

        if data.get("sourceType"):
            query = query.filter(PaymentRequestMaster.source_type == data.get("sourceType").upper())
        if data.get("brrId"):
            query = query.filter(PaymentRequestMaster.brr_id == data.get("brrId"))
        if data.get("journalId"):
            query = query.filter(PaymentRequestMaster.journal_id == data.get("journalId"))
        if data.get("vendorId"):
            query = query.filter(PaymentRequestMaster.vendor_id == data.get("vendorId"))
        if data.get("workflowStatus"):
            query = query.filter(PaymentRequestMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(db.or_(
                PaymentRequestMaster.pr_no.ilike(term),
                PaymentRequestMaster.brr_no.ilike(term),
                PaymentRequestMaster.journal_voucher_no.ilike(term),
            ))

        rows = query.order_by(PaymentRequestMaster.id.desc()).all()
        return res("Payment Request list fetched", [_payload(r, with_summary=False) for r in rows], 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS / BY UUID
# ══════════════════════════════════════════════════════════════════

def get_payment_request_details(pr_id, user_id=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "VIEW")
        if not pr.pr_uuid:
            pr.pr_uuid = str(_uuid_lib.uuid4())
            db.session.commit()
        data = _payload(pr)
        data["canEditJournal"] = has_journal_permission(pr.project_code, user_id, "EDIT") \
            if pr.source_type == SRC_JOURNAL else None
        return res("Payment Request details fetched", data, 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except Exception as e:
        return _rollback_res(e, 500)


def get_payment_request_by_uuid(pr_uuid, user_id=None):
    """Print page. BRR requests are public by uuid (same as every module);
    journal requests require a logged-in user with the journal permission."""
    try:
        pr = PaymentRequestMaster.query.filter_by(pr_uuid=pr_uuid).first()
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "VIEW")
        data = _payload(pr)
        if pr.vendor:
            data["partyAddress"] = getattr(pr.vendor, "registered_address", None)
            data["partyGstn"]    = getattr(pr.vendor, "gstin", None)
        return res("Payment Request fetched", data, 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT  (source is fixed once raised)
# ══════════════════════════════════════════════════════════════════

def edit_payment_request(pr_id, data, user_id, files=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "EDIT")
        if pr.locked:
            return res("Payment Request cannot be edited", [], 400)
        if pr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback Payment Request can be edited", [], 400)
        if not is_creator(pr.project_code, _wf(pr), user_id):
            return res("You are not Payment Request creator", [], 403)

        changed_source = (
            (data.get("sourceType") and data.get("sourceType").upper() != (pr.source_type or SRC_BRR))
            or (data.get("brrId") and str(data.get("brrId")) != str(pr.brr_id))
            or (data.get("journalId") and str(data.get("journalId")) != str(pr.journal_id))
            or (pr.source_type in (SRC_JOURNAL, SRC_ADVANCE) and data.get("vendorId")
                and str(data.get("vendorId")) != str(pr.vendor_id))
        )
        if changed_source:
            return res("Source (BRR / Journal / Advance / Vendor) cannot be changed. Raise a new Payment Request.", [], 400)

        requested = (_dec(data.get("requestedAmount"), "requestedAmount")
                     if data.get("requestedAmount") not in (None, "") else _q(pr.requested_amount))
        deduction = (_dec(data.get("deductionAmount"), "deductionAmount")
                     if "deductionAmount" in data else _q(pr.deduction_amount))
        bill, previous = _revalidate(pr, requested, deduction)

        pr.bill_amount          = bill
        pr.previously_requested = previous
        pr.requested_amount     = requested
        pr.deduction_amount     = deduction
        pr.net_payable          = requested - deduction
        _apply_common_fields(pr, data)

        doc_file = files.get("attachedDoc") if files else None
        if doc_file:
            if pr.attached_doc:
                delete_file_from_storage(pr.attached_doc)
            pr.attached_doc = upload_file_to_bunny(
                file       = doc_file,
                mainFolder = "payment_request",
                subFolder  = pr.pr_no,
                fileName   = f"attached_doc_{int(_time.time())}",
            )
        elif data.get("clearAttachedDoc") == "true" and pr.attached_doc:
            delete_file_from_storage(pr.attached_doc)
            pr.attached_doc = None

        if pr.workflow_status == "Reback":
            pr.correction_sent_at = None

        pr.updated_by = user_id
        pr.updated_at = datetime.utcnow()
        db.session.commit()

        return res("Payment Request updated", {"id": pr.id, "prNo": pr.pr_no, "attachedDoc": pr.attached_doc}, 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_payment_request(pr_id, submitted_by=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, submitted_by, "EDIT")
        if pr.workflow_status not in ["Draft", "Reback"]:
            return res("Payment Request already submitted", [], 400)
        if not is_creator(pr.project_code, _wf(pr), submitted_by):
            return res("You are not Payment Request creator", [], 403)

        bill, previous = _revalidate(pr)
        pr.bill_amount          = bill
        pr.previously_requested = previous

        if pr.workflow_status == "Reback":
            pr.current_level = 0

        first_level = get_first_approver(pr.project_code, _wf(pr))

        if not first_level:
            pr.workflow_status   = "Approved"
            pr.locked            = True
            pr.approved_by       = submitted_by
            pr.submitted_at      = datetime.utcnow()
            pr.final_approved_at = datetime.utcnow()
        else:
            pr.workflow_status = f"Pending_L{first_level.level_no}"
            pr.current_level   = first_level.level_no
            pr.locked          = True
            pr.submitted_at    = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _wf(pr),
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by,
        )

        pr.submitted_by = submitted_by
        pr.updated_by   = submitted_by
        pr.updated_at   = datetime.utcnow()
        db.session.commit()

        try:
            if first_level:
                submitter = User.query.get(submitted_by)
                wa.on_submit(
                    module_code    = _WA_CODE,
                    doc_no         = pr.pr_no,
                    uuid           = str(pr.id),
                    project_code   = pr.project_code,
                    submitter_name = submitter.username if submitter else str(submitted_by),
                    approver_user  = first_level.user,
                    current_level  = first_level.level_no,
                    record_id      = pr.id,
                )
        except Exception:
            pass

        return res(
            "Payment Request submitted",
            {"id": pr.id, "prNo": pr.pr_no, "workflowStatus": pr.workflow_status},
            200,
        )

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_payment_request(pr_id, approved_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, approved_by, "VIEW")
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not is_current_approver(pr.project_code, _wf(pr), pr.current_level, approved_by):
            return res("You are not current approver", [], 403)

        gap = get_gap_level(pr.project_code, _wf(pr), pr.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(pr.project_code, _wf(pr), pr.current_level)
        prev_level = pr.current_level

        if next_level:
            create_history(
                project_code = pr.project_code,
                module_code  = _wf(pr),
                record_id    = pr.id,
                level_no     = pr.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            pr.current_level   = next_level.level_no
            pr.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            # Final approval — balance must still hold
            _revalidate(pr)
            create_history(
                project_code = pr.project_code,
                module_code  = _wf(pr),
                record_id    = pr.id,
                level_no     = pr.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            pr.workflow_status   = "Approved"
            pr.locked            = True
            pr.approved_by       = approved_by
            pr.final_approved_at = datetime.utcnow()

        pr.updated_by = approved_by
        pr.updated_at = datetime.utcnow()
        db.session.commit()

        try:
            approver_user = User.query.get(approved_by)
            approver_name = approver_user.username if approver_user else str(approved_by)
            if next_level:
                wa.on_approve(
                    module_code        = _WA_CODE,
                    doc_no             = pr.pr_no,
                    uuid               = str(pr.id),
                    project_code       = pr.project_code,
                    approver_name      = approver_name,
                    prev_level         = prev_level,
                    next_approver_user = next_level.user,
                    next_level         = next_level.level_no,
                    record_id          = pr.id,
                )
            else:
                wa.on_final_approve(
                    module_code   = _WA_CODE,
                    doc_no        = pr.pr_no,
                    uuid          = str(pr.id),
                    project_code  = pr.project_code,
                    approver_name = approver_name,
                    creator_user  = User.query.get(pr.created_by),
                    record_id     = pr.id,
                )
        except Exception:
            pass

        return res(
            "Payment Request approved",
            {"id": pr.id, "workflowStatus": pr.workflow_status, "currentLevel": pr.current_level},
            200,
        )

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_payment_request(pr_id, reback_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, reback_by, "VIEW")
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)
        if not is_current_approver(pr.project_code, _wf(pr), pr.current_level, reback_by):
            return res("You are not current approver", [], 403)

        pr.workflow_status    = "Reback"
        pr.locked             = False
        pr.correction_sent_at = datetime.utcnow()
        pr.updated_by         = reback_by
        pr.updated_at         = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _wf(pr),
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments,
        )
        db.session.commit()

        try:
            reback_user = User.query.get(reback_by)
            wa.on_reback(
                module_code   = _WA_CODE,
                doc_no        = pr.pr_no,
                uuid          = str(pr.id),
                project_code  = pr.project_code,
                approver_name = reback_user.username if reback_user else str(reback_by),
                creator_user  = User.query.get(pr.created_by),
                comments      = comments,
                record_id     = pr.id,
            )
        except Exception:
            pass

        return res("Payment Request sent for correction",
                   {"id": pr.id, "workflowStatus": pr.workflow_status}, 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT  (frees the source balance)
# ══════════════════════════════════════════════════════════════════

def reject_payment_request(pr_id, rejected_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, rejected_by, "VIEW")
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)
        if not is_current_approver(pr.project_code, _wf(pr), pr.current_level, rejected_by):
            return res("You are not current approver", [], 403)

        pr.workflow_status = "Rejected"
        pr.locked          = True
        pr.rejected_at     = datetime.utcnow()
        pr.rejected_by     = rejected_by
        pr.status          = "Inactive"
        pr.updated_by      = rejected_by
        pr.updated_at      = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _wf(pr),
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments,
        )
        db.session.commit()

        try:
            rejected_user = User.query.get(rejected_by)
            wa.on_reject(
                module_code   = _WA_CODE,
                doc_no        = pr.pr_no,
                uuid          = str(pr.id),
                project_code  = pr.project_code,
                approver_name = rejected_user.username if rejected_user else str(rejected_by),
                creator_user  = User.query.get(pr.created_by),
                comments      = comments,
                record_id     = pr.id,
            )
        except Exception:
            pass

        return res("Payment Request rejected",
                   {"id": pr.id, "workflowStatus": pr.workflow_status}, 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY / MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_payment_request_history(pr_id, user_id=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "VIEW")

        rows = get_history(_wf(pr), pr.id)
        data = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]
        steps = get_approval_steps(pr.project_code, _wf(pr), pr, rows)

        return res("Payment Request history fetched", {
            "workflowStatus": pr.workflow_status,
            "currentLevel":   pr.current_level,
            "approvalSteps":  steps,
            "history":        data,
        }, 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def get_payment_request_my_approval_status(pr_id, user_id):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "VIEW")
        return res("Approval status", get_my_approval_status(pr.project_code, _wf(pr), pr, user_id), 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 11. DELETE (draft only)
# ══════════════════════════════════════════════════════════════════

def delete_payment_request(pr_id, user_id=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        _guard(pr, user_id, "EDIT")
        if pr.locked or pr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft / Reback Payment Request can be deleted", [], 400)
        if pr.source_type == SRC_ADVANCE and BillPaymentReceiptMaster.query.filter_by(payment_request_id=pr.id).first():
            return res("Advance payments exist against this request — it cannot be deleted", [], 400)
        if pr.attached_doc:
            try:
                delete_file_from_storage(pr.attached_doc)
            except Exception:
                pass
        db.session.delete(pr)
        db.session.commit()
        from app.modules.delete_manager.service import auto_complete_check
        auto_complete_check("PAYMENT_REQUEST", pr_id)
        return res("Payment Request deleted successfully", [], 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)



# ══════════════════════════════════════════════════════════════════
# 12. ADVANCE — vendors, payable advances, link / unlink to a bill
# ══════════════════════════════════════════════════════════════════

def get_advance_vendors(data):
    """Sundry creditors connected with the project (for an ADVANCE request)."""
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)
        rows = [
            {"vendorId": v.id, "ledgerCode": v.ledger_code, "ledgerName": v.ledger_name, "gstin": v.gstin}
            for v in _project_creditors(project_code)
        ]
        return res("Project creditors fetched", rows, 200)
    except Exception as e:
        return _rollback_res(e, 500)


def get_payable_advances(data):
    """Approved ADVANCE requests that still have something left to pay —
    the picker of Account › Payment › Advance."""
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)
        query = PaymentRequestMaster.query.filter(
            PaymentRequestMaster.project_code    == project_code,
            PaymentRequestMaster.source_type     == SRC_ADVANCE,
            PaymentRequestMaster.workflow_status == "Approved",
        )
        if data.get("vendorId"):
            query = query.filter(PaymentRequestMaster.vendor_id == int(data.get("vendorId")))
        include_id = int(data.get("includeId")) if data.get("includeId") else None

        result = []
        for pr in query.order_by(PaymentRequestMaster.id.desc()).all():
            row = _payload(pr, with_summary=False)
            if row["advanceBalance"] > 0 or pr.id == include_id:
                result.append(row)
        return res("Payable advance requests fetched", result, 200)
    except Exception as e:
        return _rollback_res(e, 500)


def _can_link(pr, user_id):
    return _is_super_admin(user_id) or is_creator(pr.project_code, _wf(pr), user_id) \
        or is_current_approver(pr.project_code, _wf(pr), pr.current_level, user_id)


def _bill_paid_after_link(pr):
    """Payments already made on the linked bill — unlinking would hand that
    balance back, so it is blocked."""
    from app.models.purchaseBill import PurchaseBillMaster
    if pr.link_type == SRC_BRR and pr.brr_id:
        bill_ids = [b.id for b in PurchaseBillMaster.query.filter_by(brr_id=pr.brr_id).all()]
        if not bill_ids:
            return None
        return (
            BillPaymentReceiptMaster.query
            .filter(BillPaymentReceiptMaster.payment_type == "bill",
                    BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids),
                    BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
                    BillPaymentReceiptMaster.created_at >= pr.linked_at)
            .first()
        )
    if pr.link_type == SRC_JOURNAL and pr.journal_id:
        return (
            BillPaymentReceiptMaster.query
            .filter(BillPaymentReceiptMaster.payment_type == "voucher",
                    BillPaymentReceiptMaster.journal_entry_id == pr.journal_id,
                    BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
                    BillPaymentReceiptMaster.created_at >= pr.linked_at)
            .first()
        )
    return None


def link_advance(pr_id, data, user_id):
    """Link an Approved ADVANCE request to an Approved BRR or journal of the
    same vendor. The advance then counts in that source's requested total
    (same balance rule as a BRR / journal request)."""
    try:
        pr = PaymentRequestMaster.query.filter(PaymentRequestMaster.id == pr_id).with_for_update().first()
        if not pr:
            return res("Payment Request not found", [], 404)
        if pr.source_type != SRC_ADVANCE:
            return res("Only an Advance Payment Request can be linked", [], 400)
        if pr.workflow_status != "Approved":
            return res("Only an Approved advance can be linked to a bill", [], 400)
        if pr.link_type:
            return res(f"Advance is already linked to {pr.link_type} {_linked_no(pr)}", [], 400)
        if not _can_link(pr, user_id):
            return res("You are not allowed to link this advance", [], 403)

        link_type = (data.get("linkType") or "").upper()
        requested = _q(pr.requested_amount)
        deduction = _q(pr.deduction_amount)

        if link_type == SRC_BRR:
            brr = _lock_brr(data.get("brrId")) if data.get("brrId") else None
            if not brr:
                return res("BRR not found", [], 404)
            if brr.project_code != pr.project_code:
                return res("BRR does not belong to this project", [], 400)
            if brr.vendor_id != pr.vendor_id:
                return res("BRR vendor does not match the advance vendor", [], 400)
            bill, previous = _validate_brr(brr, requested, deduction, exclude_id=pr.id)
            pr.brr_id         = brr.id
            pr.brr_no         = brr.brr_no
            pr.order_category = brr.order_category
            pr.party_bill_no  = brr.party_bill_no
            pr.party_date     = brr.party_date
        elif link_type == SRC_JOURNAL:
            _require_journal(pr.project_code, user_id, "EDIT")
            je = _lock_journal(data.get("journalId")) if data.get("journalId") else None
            if not je:
                return res("Journal entry not found", [], 404)
            if je.project_code != pr.project_code:
                return res("Journal entry does not belong to this project", [], 400)
            bill, previous = _validate_journal(je, pr.vendor_id, requested, deduction, exclude_id=pr.id)
            pr.journal_id         = je.id
            pr.journal_voucher_no = je.voucher_no
            pr.journal_date       = je.entry_date
        else:
            return res("linkType must be BRR or JOURNAL", [], 400)

        pr.link_type            = link_type
        pr.linked_at            = datetime.utcnow()
        pr.linked_by            = user_id
        pr.bill_amount          = bill
        pr.previously_requested = previous
        pr.updated_by           = user_id
        pr.updated_at           = datetime.utcnow()
        db.session.commit()
        return res(f"Advance linked to {link_type} {_linked_no(pr)}", _payload(pr), 200)

    except _Forbidden as e:
        return _rollback_res(e, 403)
    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def unlink_advance(pr_id, user_id):
    try:
        pr = PaymentRequestMaster.query.filter(PaymentRequestMaster.id == pr_id).with_for_update().first()
        if not pr:
            return res("Payment Request not found", [], 404)
        if pr.source_type != SRC_ADVANCE or not pr.link_type:
            return res("This advance is not linked", [], 400)
        if not _can_link(pr, user_id):
            return res("You are not allowed to unlink this advance", [], 403)
        if pr.link_type == SRC_JOURNAL:
            _require_journal(pr.project_code, user_id, "EDIT")
        blocker = _bill_paid_after_link(pr)
        if blocker:
            return res(
                f"Payment {blocker.receipt_no} was made on the linked bill after this link — unlink is blocked",
                [], 400,
            )
        pr.brr_id = pr.journal_id = None
        pr.brr_no = pr.journal_voucher_no = None
        pr.journal_date = pr.party_date = None
        pr.order_category = pr.party_bill_no = None
        pr.link_type = pr.linked_at = pr.linked_by = None
        pr.bill_amount = pr.previously_requested = Decimal("0.00")
        pr.updated_by = user_id
        pr.updated_at = datetime.utcnow()
        db.session.commit()
        return res("Advance unlinked", _payload(pr), 200)
    except _Forbidden as e:
        return _rollback_res(e, 403)
    except Exception as e:
        return _rollback_res(e, 500)
