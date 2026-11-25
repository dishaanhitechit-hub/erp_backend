"""
Advance Adjustment + Vendor Advance Register
────────────────────────────────────────────
An advance is paid with no bill (Account › Payment › Advance against an
Approved ADVANCE Payment Request) and sits in the Vendor Advance Register as
the vendor's OUTSTANDING advance.

An Advance Adjustment settles part of it against ONE bill of the same vendor
and project:
  • BRR type     → an Approved Purchase Bill (of a BRR)
  • JOURNAL type → an Approved Journal Entry with the vendor's Cr lines
One advance can be adjusted against many bills, in parts (partial / multiple
settlements); a bill can take many advances. All bills of one advance are of
one type.

The amount is split product / CC wise over the bill's rows — auto-filled row
by row (first product first, then the next, GST last) and editable.

Rules
  • available advance   = approved advance payments − active adjustments
  • adjusted amount    ≤ available advance
  • each row           ≤ row booked − paid / in progress − already adjusted
  • the bill           ≤ bill open balance (and the BRR / journal amount not
                         yet requested through Payment Requests)
  • once adjusted, the amount lowers the bill's balance in Account › Payment
    and counts in the BRR's / journal's "already requested".

Ledger (source_type "advance_adjustment"):
    Dr Vendor   per row, tagged with the row's CC (cost_centre_code)
    Cr Vendor   total, untagged (the advance)
Cancel → reversal (-REV); the record is kept as Cancelled.
"""
from app.utils.date_utils import created_ts
from decimal import Decimal
from datetime import datetime, date

from sqlalchemy import func

from app.extensions import db
from app.models.advanceAdjustment import AdvanceAdjustmentMaster, AdvanceAdjustmentLine
from app.models.billPaymentReceipt import (
    BillPaymentReceiptMaster, BillPaymentReceiptItem, BillPaymentReceiptGst,
)
from app.models.purchaseBill import PurchaseBillMaster, PurchaseBillItem
from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.paymentRequest import PaymentRequestMaster
from app.models.vendor import Vendor
from app.models.user import User
from app.response import res
from app.utils.date_utils import parse_date

SOURCE_TYPE = "advance_adjustment"
BRR, JOURNAL = "BRR", "JOURNAL"
_DEAD = ("Rejected", "Cancelled")
_ACTIVE = "Approved"
_TWO = Decimal("0.01")


class _Forbidden(Exception):
    pass


def _D(v):
    return Decimal(str(v or 0)).quantize(_TWO)


def _f(v):
    return float(_D(v))


def _fmt(d):
    if not d:
        return None
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def _gst_plain(gst_type):
    return (gst_type or "").split(":", 1)[-1]


def _uid(user_id):
    try:
        return int(user_id) if user_id else None
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════
# AMOUNTS
# ══════════════════════════════════════════════════════════════════

def advance_paid_approved(pr_id):
    q = db.session.query(func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0)).filter(
        BillPaymentReceiptMaster.payment_type       == "advance",
        BillPaymentReceiptMaster.payment_request_id == pr_id,
        BillPaymentReceiptMaster.workflow_status    == "Approved",
    )
    return _D(q.scalar())


def adjusted_on_request(pr_id, exclude_id=None):
    q = db.session.query(func.coalesce(func.sum(AdvanceAdjustmentMaster.amount), 0)).filter(
        AdvanceAdjustmentMaster.payment_request_id == pr_id,
        AdvanceAdjustmentMaster.workflow_status    == _ACTIVE,
    )
    if exclude_id:
        q = q.filter(AdvanceAdjustmentMaster.id != exclude_id)
    return _D(q.scalar())


def available_advance(pr):
    """Paid (approved) on the advance request and not adjusted yet."""
    return max(advance_paid_approved(pr.id) - adjusted_on_request(pr.id), Decimal("0.00"))


def adjusted_by_bill(bill_ids):
    """{purchase bill id: active adjusted amount}."""
    ids = [i for i in bill_ids if i]
    if not ids:
        return {}
    rows = (db.session.query(AdvanceAdjustmentMaster.purchase_bill_id, func.sum(AdvanceAdjustmentMaster.amount))
            .filter(AdvanceAdjustmentMaster.purchase_bill_id.in_(ids),
                    AdvanceAdjustmentMaster.workflow_status == _ACTIVE)
            .group_by(AdvanceAdjustmentMaster.purchase_bill_id).all())
    return {k: float(v or 0) for k, v in rows}


def adjusted_by_journal(je_ids, vendor_id=None):
    """{journal id: active adjusted amount} (optionally one vendor)."""
    ids = [i for i in je_ids if i]
    if not ids:
        return {}
    q = (db.session.query(AdvanceAdjustmentMaster.journal_id, func.sum(AdvanceAdjustmentMaster.amount))
         .filter(AdvanceAdjustmentMaster.journal_id.in_(ids),
                 AdvanceAdjustmentMaster.workflow_status == _ACTIVE))
    if vendor_id:
        q = q.filter(AdvanceAdjustmentMaster.vendor_id == vendor_id)
    return {k: float(v or 0) for k, v in q.group_by(AdvanceAdjustmentMaster.journal_id).all()}


def adjusted_on_brr(brr_id):
    q = db.session.query(func.coalesce(func.sum(AdvanceAdjustmentMaster.amount), 0)).filter(
        AdvanceAdjustmentMaster.brr_id == brr_id, AdvanceAdjustmentMaster.workflow_status == _ACTIVE)
    return _D(q.scalar())


def adjusted_on_journal_vendor(journal_id, vendor_id):
    q = db.session.query(func.coalesce(func.sum(AdvanceAdjustmentMaster.amount), 0)).filter(
        AdvanceAdjustmentMaster.journal_id == journal_id,
        AdvanceAdjustmentMaster.vendor_id == vendor_id,
        AdvanceAdjustmentMaster.workflow_status == _ACTIVE)
    return _D(q.scalar())


def adjusted_row_maps(purchase_bill_ids=(), je_ids=(), exclude_id=None):
    """Adjusted amounts per bill row:
        items  {pb_item_id: amt}
        gst    {(bill_id, "IGST"): amt}
        lines  {je_line_id: amt}"""
    items, gst, lines = {}, {}, {}
    q = (db.session.query(AdvanceAdjustmentLine, AdvanceAdjustmentMaster)
         .join(AdvanceAdjustmentMaster, AdvanceAdjustmentLine.adjustment_id == AdvanceAdjustmentMaster.id)
         .filter(AdvanceAdjustmentMaster.workflow_status == _ACTIVE))
    conds = []
    if purchase_bill_ids:
        conds.append(AdvanceAdjustmentMaster.purchase_bill_id.in_(list(purchase_bill_ids)))
    if je_ids:
        conds.append(AdvanceAdjustmentMaster.journal_id.in_(list(je_ids)))
    if not conds:
        return items, gst, lines
    q = q.filter(db.or_(*conds))
    if exclude_id:
        q = q.filter(AdvanceAdjustmentMaster.id != exclude_id)
    for line, adj in q.all():
        amt = float(line.amount or 0)
        if line.line_type == "item" and line.pb_item_id:
            items[line.pb_item_id] = items.get(line.pb_item_id, 0.0) + amt
        elif line.line_type == "gst":
            key = (adj.purchase_bill_id, _gst_plain(line.gst_type))
            gst[key] = gst.get(key, 0.0) + amt
        elif line.line_type == "journal" and line.je_line_id:
            lines[line.je_line_id] = lines.get(line.je_line_id, 0.0) + amt
    return items, gst, lines


# ══════════════════════════════════════════════════════════════════
# BILL ROWS (what can still be adjusted, row by row)
# ══════════════════════════════════════════════════════════════════

def _used_item_map(pb_item_ids):
    """Bill / voucher payments on basic rows — approved AND in progress."""
    if not pb_item_ids:
        return {}
    q = (db.session.query(BillPaymentReceiptItem.pb_item_id, func.sum(BillPaymentReceiptItem.current_amount))
         .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptItem.receipt_id)
         .filter(BillPaymentReceiptItem.pb_item_id.in_(pb_item_ids),
                 BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
                 BillPaymentReceiptMaster.payment_type != "advance")
         .group_by(BillPaymentReceiptItem.pb_item_id))
    return {k: float(v or 0) for k, v in q.all()}


def _used_gst_map(bill_id):
    """Payments on GST rows of a bill (plain "IGST" on a single-bill payment,
    "billId:IGST" on a multi-bill one) — approved AND in progress."""
    prefix = f"{bill_id}:"
    q = (db.session.query(BillPaymentReceiptGst.gst_type, func.sum(BillPaymentReceiptGst.current_amount))
         .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptGst.receipt_id)
         .filter(db.or_(db.and_(BillPaymentReceiptMaster.purchase_bill_id == bill_id,
                                ~BillPaymentReceiptGst.gst_type.contains(":")),
                        BillPaymentReceiptGst.gst_type.startswith(prefix)),
                 BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
                 BillPaymentReceiptMaster.payment_type != "advance")
         .group_by(BillPaymentReceiptGst.gst_type))
    out = {}
    for k, v in q.all():
        out[_gst_plain(k)] = out.get(_gst_plain(k), 0.0) + float(v or 0)
    return out


def _used_je_line_map(je_id):
    line_ids = [l.id for l in JournalEntryLine.query.filter_by(journal_id=je_id).with_entities(JournalEntryLine.id)]
    if not line_ids:
        return {}
    q = (db.session.query(BillPaymentReceiptItem.je_line_id, func.sum(BillPaymentReceiptItem.current_amount))
         .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptItem.receipt_id)
         .filter(BillPaymentReceiptItem.je_line_id.in_(line_ids),
                 BillPaymentReceiptMaster.workflow_status.notin_(_DEAD),
                 BillPaymentReceiptMaster.payment_type != "advance")
         .group_by(BillPaymentReceiptItem.je_line_id))
    return {k: float(v or 0) for k, v in q.all()}


def bill_payment_totals(bill_ids):
    """(approved, in progress) bill payments per purchase bill."""
    if not bill_ids:
        return {}, {}
    base = db.session.query(
        BillPaymentReceiptMaster.purchase_bill_id,
        func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0),
    ).filter(BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids),
             BillPaymentReceiptMaster.payment_type != "advance")
    paid = dict(base.filter(BillPaymentReceiptMaster.workflow_status == "Approved")
                .group_by(BillPaymentReceiptMaster.purchase_bill_id).all())
    inprog = dict(base.filter(BillPaymentReceiptMaster.workflow_status.notin_(("Approved",) + _DEAD))
                  .group_by(BillPaymentReceiptMaster.purchase_bill_id).all())
    return {k: float(v) for k, v in paid.items()}, {k: float(v) for k, v in inprog.items()}


def _order_no(bill):
    brr = bill.brr
    return ((brr.order.order_no if brr and brr.order else None)
            or (brr.pw_order.order_no if brr and brr.pw_order else None))


def purchase_bill_rows(bill, exclude_id=None):
    """Basic rows then selected GST rows of a purchase bill:
    booked / paid (incl. in progress) / adjusted / balance."""
    used_items = _used_item_map([i.id for i in bill.items])
    used_gst = _used_gst_map(bill.id)
    adj_items, adj_gst, _ = adjusted_row_maps(purchase_bill_ids=[bill.id], exclude_id=exclude_id)
    rows = []
    for i in sorted(bill.items, key=lambda x: (x.sl_no or 0, x.id)):
        booked = float(i.basic_amount or 0)
        paid = used_items.get(i.id, 0.0)
        adj = adj_items.get(i.id, 0.0)
        rows.append({
            "key": f"i:{i.id}", "lineType": "item", "pbItemId": i.id, "gstType": None, "jeLineId": None,
            "slNo": i.sl_no, "ccCode": i.cc_code, "ccName": i.cc_name, "description": i.description,
            "bookedAmount": round(booked, 2), "paidAmount": round(paid, 2), "adjustedAmount": round(adj, 2),
            "balanceAmount": round(max(booked - paid - adj, 0), 2), "amount": 0.0,
        })
    for g in bill.gst_lines:
        if not g.is_selected:
            continue
        booked = float(g.gst_amount or 0)
        paid = used_gst.get(g.gst_type, 0.0)
        adj = adj_gst.get((bill.id, g.gst_type), 0.0)
        rows.append({
            "key": f"g:{g.gst_type}", "lineType": "gst", "pbItemId": None, "gstType": g.gst_type, "jeLineId": None,
            "slNo": None, "ccCode": g.cc_code, "ccName": g.cc_name,
            "description": f"{g.gst_type} @ {float(g.percent or 0):g}%",
            "bookedAmount": round(booked, 2), "paidAmount": round(paid, 2), "adjustedAmount": round(adj, 2),
            "balanceAmount": round(max(booked - paid - adj, 0), 2), "amount": 0.0,
        })
    return rows


def journal_rows(je, exclude_id=None):
    """Dr CC lines of a journal: booked / paid (incl. in progress) / adjusted / balance."""
    used = _used_je_line_map(je.id)
    _, _, adj_lines = adjusted_row_maps(je_ids=[je.id], exclude_id=exclude_id)
    rows = []
    dr = [l for l in sorted(je.lines, key=lambda x: x.id) if l.dr_cr == "Dr" and l.account_type == "CC"]
    for idx, l in enumerate(dr, start=1):
        booked = float(l.debit_amount or 0)
        paid = used.get(l.id, 0.0)
        adj = adj_lines.get(l.id, 0.0)
        rows.append({
            "key": f"j:{l.id}", "lineType": "journal", "pbItemId": None, "gstType": None, "jeLineId": l.id,
            "slNo": idx, "ccCode": l.cc.cc_code if l.cc else None, "ccName": l.cc.cc_name if l.cc else None,
            "description": getattr(l, "narration", None) or "",
            "bookedAmount": round(booked, 2), "paidAmount": round(paid, 2), "adjustedAmount": round(adj, 2),
            "balanceAmount": round(max(booked - paid - adj, 0), 2), "amount": 0.0,
        })
    return rows


def fill_rows(rows, amount):
    """Default split: first row fills to its balance, then the next."""
    left = round(float(amount or 0), 2)
    for r in rows:
        take = round(min(left, max(float(r["balanceAmount"]), 0)), 2) if left > 0 else 0.0
        r["amount"] = take
        left = round(left - take, 2)
    return rows


def _journal_vendor_bill(je_id, vendor_id):
    return _D(db.session.query(func.coalesce(func.sum(JournalEntryLine.credit_amount), 0)).filter(
        JournalEntryLine.journal_id == je_id, JournalEntryLine.dr_cr == "Cr",
        JournalEntryLine.vendor_id == vendor_id).scalar())


def _journal_vendor_paid(je_id, vendor_id):
    return _D(db.session.query(func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0)).filter(
        BillPaymentReceiptMaster.journal_entry_id == je_id,
        BillPaymentReceiptMaster.vendor_id == vendor_id,
        BillPaymentReceiptMaster.payment_type == "voucher",
        BillPaymentReceiptMaster.workflow_status.notin_(_DEAD)).scalar())


def _requested_left_brr(brr_id, exclude_adj_id=None):
    """BRR amount not yet requested (BRR Payment Requests + adjustments)."""
    from app.modules.billing.payment_request.service import brr_request_balance
    left = brr_request_balance(brr_id)
    if exclude_adj_id:
        adj = AdvanceAdjustmentMaster.query.get(exclude_adj_id)
        if adj and adj.workflow_status == _ACTIVE and adj.brr_id == brr_id:
            left += _D(adj.amount)
    return left


def bill_caps(pr, link_type, bill=None, je=None, exclude_id=None):
    """(rows, bill open, request-side room) for adjusting this advance on a bill."""
    if link_type == BRR:
        rows = purchase_bill_rows(bill, exclude_id)
        paid, inprog = bill_payment_totals([bill.id])
        adjusted = adjusted_by_bill([bill.id]).get(bill.id, 0.0)
        if exclude_id:
            adj = AdvanceAdjustmentMaster.query.get(exclude_id)
            if adj and adj.purchase_bill_id == bill.id and adj.workflow_status == _ACTIVE:
                adjusted -= float(adj.amount or 0)
        open_bal = _D(max(float(bill.total_invoice_amount or 0) - paid.get(bill.id, 0)
                          - inprog.get(bill.id, 0) - adjusted, 0))
        room = _requested_left_brr(bill.brr_id, exclude_id) if bill.brr_id else None
        return rows, open_bal, room
    rows = journal_rows(je, exclude_id)
    bill_amt = _journal_vendor_bill(je.id, pr.vendor_id)
    adjusted = adjusted_on_journal_vendor(je.id, pr.vendor_id)
    if exclude_id:
        adj = AdvanceAdjustmentMaster.query.get(exclude_id)
        if adj and adj.journal_id == je.id and adj.workflow_status == _ACTIVE:
            adjusted -= _D(adj.amount)
    open_bal = max(bill_amt - _journal_vendor_paid(je.id, pr.vendor_id) - adjusted, Decimal("0.00"))
    from app.modules.billing.payment_request.service import journal_request_balance
    room = journal_request_balance(je.id, pr.vendor_id)
    return rows, open_bal, room


# ══════════════════════════════════════════════════════════════════
# LOOKUPS / GUARDS
# ══════════════════════════════════════════════════════════════════

def _is_super_admin(user_id):
    user = User.query.get(_uid(user_id)) if _uid(user_id) else None
    return bool(user and user.global_role and user.global_role.name == "super_admin")


def _journal_allowed(project_code, user_id, action="VIEW"):
    from app.modules.billing.payment_request.service import has_journal_permission
    return has_journal_permission(project_code, user_id, action)


def _can_adjust(pr, user_id):
    """Super admin; the advance request's creator / approvers; or anyone who
    can make payments (Account › Payment creator) in the project."""
    from app.modules.work_flow import is_creator, is_current_approver
    from app.models.approval_path import ApprovalPath
    if _is_super_admin(user_id):
        return True
    uid = _uid(user_id)
    if pr.created_by == uid or pr.approved_by == uid:
        return True
    try:
        if is_creator(pr.project_code, "payment", uid) or is_creator(pr.project_code, "payment_request", uid):
            return True
        if is_current_approver(pr.project_code, "payment_request", pr.current_level, uid):
            return True
        return ApprovalPath.query.filter_by(project_code=pr.project_code, user_id=uid).filter(
            ApprovalPath.module_code.in_(("payment", "payment_request"))).first() is not None
    except Exception:
        db.session.rollback()
        return False


def locked_type(pr, exclude_id=None):
    """The bill type this advance is already adjusted against (one type per advance)."""
    q = AdvanceAdjustmentMaster.query.filter(
        AdvanceAdjustmentMaster.payment_request_id == pr.id,
        AdvanceAdjustmentMaster.workflow_status == _ACTIVE)
    if exclude_id:
        q = q.filter(AdvanceAdjustmentMaster.id != exclude_id)
    adj = q.first()
    return adj.link_type if adj else None


def _get_advance_request(pr_id, for_update=False):
    q = PaymentRequestMaster.query.filter(PaymentRequestMaster.id == int(pr_id or 0))
    if for_update:
        q = q.with_for_update()
    pr = q.first()
    if not pr or pr.source_type != "ADVANCE":
        raise LookupError("Advance Payment Request not found")
    return pr


def _fy_locked(d):
    from app.models.accounting import FinancialYear
    fy = FinancialYear.query.filter(FinancialYear.start_date <= d, FinancialYear.end_date >= d).first()
    return fy if fy and fy.is_locked else None


def _resolve_bill(pr, data, for_update=False):
    """(link_type, purchase bill | None, journal | None) from purchaseBillId / journalId."""
    if data.get("purchaseBillId"):
        q = PurchaseBillMaster.query.filter(PurchaseBillMaster.id == int(data["purchaseBillId"]))
        bill = (q.with_for_update() if for_update else q).first()
        if not bill:
            raise LookupError("Purchase Bill not found")
        if bill.workflow_status != "Approved":
            raise ValueError(f"Purchase Bill {bill.purchase_bill_no} is not Approved")
        if bill.project_code != pr.project_code:
            raise ValueError("Purchase Bill does not belong to this project")
        if bill.vendor_id != pr.vendor_id:
            raise ValueError("Purchase Bill vendor does not match the advance vendor")
        return BRR, bill, None
    if data.get("journalId"):
        q = JournalEntryMaster.query.filter(JournalEntryMaster.id == int(data["journalId"]))
        je = (q.with_for_update() if for_update else q).first()
        if not je:
            raise LookupError("Journal entry not found")
        if je.workflow_status != "Approved":
            raise ValueError(f"Journal {je.voucher_no} is not Approved")
        if je.project_code != pr.project_code:
            raise ValueError("Journal entry does not belong to this project")
        if _journal_vendor_bill(je.id, pr.vendor_id) <= 0:
            raise ValueError(f"The advance vendor has no Cr entry in journal {je.voucher_no}")
        return JOURNAL, None, je
    raise ValueError("purchaseBillId or journalId required")


# ══════════════════════════════════════════════════════════════════
# PAYLOADS
# ══════════════════════════════════════════════════════════════════

def adjustment_payload(a, with_lines=True):
    data = {
        "id":               a.id,
        "uuid":             a.adjustment_uuid,
        "adjustmentNo":     a.adjustment_no,
        "adjustmentDate":   _fmt(a.adjustment_date),
        "projectCode":      a.project_code,
        "vendorId":         a.vendor_id,
        "partyName":        a.vendor.ledger_name if a.vendor else None,
        "paymentRequestId": a.payment_request_id,
        "paymentRequestNo": a.payment_request.pr_no if a.payment_request else None,
        "linkType":         a.link_type,
        "purchaseBillId":   a.purchase_bill_id,
        "brrId":            a.brr_id,
        "brrNo":            a.purchase_bill.brr_no if a.purchase_bill else None,
        "journalId":        a.journal_id,
        "billNo":           a.bill_no,
        "amount":           _f(a.amount),
        "remarks":          a.remarks,
        "workflowStatus":   a.workflow_status,
        "createdBy":        a.creator.username if a.creator else None,
        "createdAt":        _fmt(a.created_at),
        "cancelledBy":      a.canceller.username if a.canceller else None,
        "cancelledAt":      _fmt(a.cancelled_at),
        "cancelReason":     a.cancel_reason,
    }
    if with_lines:
        data["lines"] = [{
            "slNo": l.sl_no, "lineType": l.line_type, "pbItemId": l.pb_item_id, "gstType": l.gst_type,
            "jeLineId": l.je_line_id, "ccCode": l.cc_code, "ccName": l.cc_name, "description": l.description,
            "bookedAmount": _f(l.booked_amount), "amount": _f(l.amount),
        } for l in a.lines]
    return data


def advance_status(pr):
    """Paid / adjusted / outstanding of one advance request (+ its adjustments)."""
    paid = advance_paid_approved(pr.id)
    adjusted = adjusted_on_request(pr.id)
    adjs = (AdvanceAdjustmentMaster.query.filter_by(payment_request_id=pr.id)
            .order_by(AdvanceAdjustmentMaster.id.asc()).all())
    return {
        "advancePaidApproved": float(paid),
        "advanceAdjusted":     float(adjusted),
        "advanceOutstanding":  float(max(paid - adjusted, Decimal("0.00"))),
        "adjustType":          locked_type(pr),
        "adjustments":         [adjustment_payload(a, with_lines=False) for a in adjs],
    }


def _generate_no():
    last = (db.session.query(AdvanceAdjustmentMaster.adjustment_no)
            .order_by(AdvanceAdjustmentMaster.id.desc()).with_for_update().first())
    num = 0
    if last and last[0]:
        try:
            num = int(last[0][3:]) if last[0].startswith("ADJ") else int(last[0])
        except ValueError:
            num = AdvanceAdjustmentMaster.query.count()
    return f"ADJ{str(num + 1).zfill(3)}"


# ══════════════════════════════════════════════════════════════════
# API — register, outstanding, bills, rows
# ══════════════════════════════════════════════════════════════════

def _err(e, code):
    db.session.rollback()
    return res(str(e), [], code)


def get_register(data, user_id=None):
    """Vendor Advance Register: vendor-wise advance paid / adjusted /
    outstanding for a project, with each advance request under it.
    ?projectCode= [&vendorId=] [&outstandingOnly=1]"""
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)
        q = PaymentRequestMaster.query.filter(
            PaymentRequestMaster.project_code == project_code,
            PaymentRequestMaster.source_type == "ADVANCE",
            PaymentRequestMaster.workflow_status == "Approved",
        )
        if data.get("vendorId"):
            q = q.filter(PaymentRequestMaster.vendor_id == int(data["vendorId"]))
        only_open = str(data.get("outstandingOnly") or "").lower() in ("1", "true", "yes")

        vendors = {}
        for pr in q.order_by(PaymentRequestMaster.id.asc()).all():
            paid = advance_paid_approved(pr.id)
            adjusted = adjusted_on_request(pr.id)
            outstanding = max(paid - adjusted, Decimal("0.00"))
            if only_open and outstanding <= 0:
                continue
            v = vendors.setdefault(pr.vendor_id, {
                "vendorId": pr.vendor_id,
                "partyName": pr.vendor.ledger_name if pr.vendor else None,
                "ledgerCode": pr.vendor.ledger_code if pr.vendor else None,
                "requested": 0.0, "paid": 0.0, "adjusted": 0.0, "outstanding": 0.0, "advances": [],
            })
            v["requested"] = round(v["requested"] + _f(pr.net_payable), 2)
            v["paid"] = round(v["paid"] + float(paid), 2)
            v["adjusted"] = round(v["adjusted"] + float(adjusted), 2)
            v["outstanding"] = round(v["outstanding"] + float(outstanding), 2)
            v["advances"].append({
                "paymentRequestId": pr.id, "uuid": pr.pr_uuid, "prNo": pr.pr_no, "prDate": _fmt(pr.pr_date),
                "netPayable": _f(pr.net_payable), "paid": float(paid), "adjusted": float(adjusted),
                "outstanding": float(outstanding), "adjustType": locked_type(pr),
                "createdTs": created_ts(pr.created_at),
            })
        rows = sorted(vendors.values(), key=lambda r: (r["partyName"] or ""))
        totals = {k: round(sum(r[k] for r in rows), 2) for k in ("requested", "paid", "adjusted", "outstanding")}
        return res("Vendor advance register fetched", {"vendors": rows, "totals": totals}, 200)
    except Exception as e:
        return _err(e, 500)


def get_adjustable_bills(data, user_id=None):
    """Bills an advance can be adjusted against: the vendor's Approved
    Purchase Bills (BRR type) and Approved journals with its Cr lines
    (JOURNAL type), with open balance. Locked to the advance's type once
    it has an adjustment. ?paymentRequestId="""
    try:
        pr = _get_advance_request(data.get("paymentRequestId"))
        lock = locked_type(pr)
        out = []
        if lock in (None, BRR):
            bills = (PurchaseBillMaster.query
                     .filter(PurchaseBillMaster.project_code == pr.project_code,
                             PurchaseBillMaster.vendor_id == pr.vendor_id,
                             PurchaseBillMaster.workflow_status == "Approved")
                     .order_by(PurchaseBillMaster.id.asc()).all())
            ids = [b.id for b in bills]
            paid, inprog = bill_payment_totals(ids)
            adj = adjusted_by_bill(ids)
            for b in bills:
                booked = float(b.total_invoice_amount or 0)
                bal = max(booked - paid.get(b.id, 0) - inprog.get(b.id, 0) - adj.get(b.id, 0), 0)
                if bal <= 0:
                    continue
                out.append({
                    "linkType": BRR, "purchaseBillId": b.id, "journalId": None,
                    "billNo": b.purchase_bill_no, "billDate": _fmt(getattr(b, "processing_date", None)),
                    "brrId": b.brr_id, "brrNo": b.brr_no, "partyBillNo": getattr(b, "vendor_bill_no", None),
                    "orderNo": _order_no(b), "bookedAmount": round(booked, 2),
                    "paidAmount": round(paid.get(b.id, 0) + inprog.get(b.id, 0), 2),
                    "adjustedAmount": round(adj.get(b.id, 0), 2), "balanceAmount": round(bal, 2),
                })
        if lock in (None, JOURNAL) and _journal_allowed(pr.project_code, user_id, "VIEW"):
            jes = (JournalEntryMaster.query
                   .join(JournalEntryLine, JournalEntryLine.journal_id == JournalEntryMaster.id)
                   .filter(JournalEntryMaster.project_code == pr.project_code,
                           JournalEntryMaster.workflow_status == "Approved",
                           JournalEntryLine.dr_cr == "Cr", JournalEntryLine.vendor_id == pr.vendor_id)
                   .distinct().order_by(JournalEntryMaster.id.asc()).all())
            adj = adjusted_by_journal([j.id for j in jes], pr.vendor_id)
            for je in jes:
                booked = _journal_vendor_bill(je.id, pr.vendor_id)
                used = _journal_vendor_paid(je.id, pr.vendor_id)
                bal = max(float(booked - used) - adj.get(je.id, 0), 0)
                if bal <= 0:
                    continue
                out.append({
                    "linkType": JOURNAL, "purchaseBillId": None, "journalId": je.id,
                    "billNo": je.voucher_no, "billDate": _fmt(je.entry_date), "brrId": None, "brrNo": None,
                    "partyBillNo": None, "orderNo": None, "bookedAmount": float(booked),
                    "paidAmount": float(used), "adjustedAmount": round(adj.get(je.id, 0), 2),
                    "balanceAmount": round(bal, 2),
                })
        return res("Adjustable bills fetched", {"adjustType": lock, "bills": out}, 200)
    except LookupError as e:
        return _err(e, 404)
    except Exception as e:
        return _err(e, 500)


def get_bill_advances(data, user_id=None):
    """Notice on a bill: the vendor's advances with something outstanding that
    can be adjusted against this bill (type rule respected), with the bill's
    open balance. ?purchaseBillId= | ?journalId=&vendorId="""
    try:
        if data.get("purchaseBillId"):
            bill = PurchaseBillMaster.query.get(int(data["purchaseBillId"]))
            if not bill:
                return res("Purchase Bill not found", [], 404)
            project_code, vendor_id, kind = bill.project_code, bill.vendor_id, BRR
            paid, inprog = bill_payment_totals([bill.id])
            open_bal = max(float(bill.total_invoice_amount or 0) - paid.get(bill.id, 0) - inprog.get(bill.id, 0)
                           - adjusted_by_bill([bill.id]).get(bill.id, 0), 0)
            adjusted_here = adjusted_by_bill([bill.id]).get(bill.id, 0)
            adj_q = AdvanceAdjustmentMaster.query.filter_by(purchase_bill_id=bill.id)
            approved = bill.workflow_status == "Approved"
        elif data.get("journalId") and data.get("vendorId"):
            je = JournalEntryMaster.query.get(int(data["journalId"]))
            if not je:
                return res("Journal entry not found", [], 404)
            project_code, vendor_id, kind = je.project_code, int(data["vendorId"]), JOURNAL
            adjusted_here = float(adjusted_on_journal_vendor(je.id, vendor_id))
            open_bal = max(float(_journal_vendor_bill(je.id, vendor_id) - _journal_vendor_paid(je.id, vendor_id))
                           - adjusted_here, 0)
            adj_q = AdvanceAdjustmentMaster.query.filter_by(journal_id=je.id, vendor_id=vendor_id)
            approved = je.workflow_status == "Approved"
        else:
            return res("purchaseBillId, or journalId and vendorId, required", [], 400)

        advances = []
        for pr in (PaymentRequestMaster.query
                   .filter(PaymentRequestMaster.project_code == project_code,
                           PaymentRequestMaster.vendor_id == vendor_id,
                           PaymentRequestMaster.source_type == "ADVANCE",
                           PaymentRequestMaster.workflow_status == "Approved")
                   .order_by(PaymentRequestMaster.id.asc()).all()):
            lock = locked_type(pr)
            avail = available_advance(pr)
            if avail <= 0 or (lock and lock != kind):
                continue
            advances.append({"paymentRequestId": pr.id, "prNo": pr.pr_no, "prDate": _fmt(pr.pr_date),
                             "outstanding": float(avail), "adjustType": lock})
        return res("Vendor advances for bill fetched", {
            "billApproved":  approved,
            "openBalance":   round(open_bal, 2),
            "adjustedHere":  round(adjusted_here, 2),
            "outstanding":   round(sum(a["outstanding"] for a in advances), 2),
            "advances":      advances,
            "adjustments":   [adjustment_payload(a, with_lines=False)
                              for a in adj_q.order_by(AdvanceAdjustmentMaster.id.asc()).all()],
        }, 200)
    except Exception as e:
        return _err(e, 500)


def get_adjustment_rows(data, user_id=None):
    """The product / CC rows of one bill for one advance, auto-filled with
    ?amount= (default: the most that can be adjusted).
    ?paymentRequestId=&purchaseBillId=|journalId=[&amount=]"""
    try:
        pr = _get_advance_request(data.get("paymentRequestId"))
        link_type, bill, je = _resolve_bill(pr, data)
        if link_type == JOURNAL and not _journal_allowed(pr.project_code, user_id, "VIEW"):
            raise _Forbidden("You do not have permission for journal entries")
        rows, open_bal, room = bill_caps(pr, link_type, bill, je)
        available = available_advance(pr)
        row_room = _D(sum(r["balanceAmount"] for r in rows))
        caps = [available, open_bal, row_room] + ([room] if room is not None else [])
        max_amt = max(min(caps), Decimal("0.00"))
        amount = _D(data["amount"]) if data.get("amount") not in (None, "") else max_amt
        fill_rows(rows, min(amount, max_amt))
        return res("Adjustment rows fetched", {
            "linkType": link_type, "adjustType": locked_type(pr),
            "billNo": bill.purchase_bill_no if bill else je.voucher_no,
            "available": float(available), "billOpen": float(open_bal),
            "requestRoom": None if room is None else float(room),
            "maxAmount": float(max_amt), "amount": float(min(amount, max_amt)), "rows": rows,
        }, 200)
    except _Forbidden as e:
        return _err(e, 403)
    except LookupError as e:
        return _err(e, 404)
    except ValueError as e:
        return _err(e, 400)
    except Exception as e:
        return _err(e, 500)


def get_adjustment_list(data, user_id=None):
    """?paymentRequestId= | ?purchaseBillId= | ?journalId= | ?projectCode= [&vendorId=]"""
    try:
        q = AdvanceAdjustmentMaster.query
        if data.get("paymentRequestId"):
            q = q.filter(AdvanceAdjustmentMaster.payment_request_id == int(data["paymentRequestId"]))
        elif data.get("purchaseBillId"):
            q = q.filter(AdvanceAdjustmentMaster.purchase_bill_id == int(data["purchaseBillId"]))
        elif data.get("journalId"):
            q = q.filter(AdvanceAdjustmentMaster.journal_id == int(data["journalId"]))
        elif data.get("projectCode"):
            q = q.filter(AdvanceAdjustmentMaster.project_code == data["projectCode"])
        else:
            return res("A filter is required", [], 400)
        if data.get("vendorId"):
            q = q.filter(AdvanceAdjustmentMaster.vendor_id == int(data["vendorId"]))
        rows = [adjustment_payload(a) for a in q.order_by(AdvanceAdjustmentMaster.id.desc()).all()]
        return res("Advance adjustments fetched", rows, 200)
    except Exception as e:
        return _err(e, 500)


def get_adjustment(adj_id, user_id=None):
    a = AdvanceAdjustmentMaster.query.get(adj_id)
    if not a:
        return res("Advance adjustment not found", [], 404)
    return res("Advance adjustment fetched", adjustment_payload(a), 200)


# ══════════════════════════════════════════════════════════════════
# CREATE / CANCEL
# ══════════════════════════════════════════════════════════════════

def _build_lines(rows, sent):
    """Validate the split sent by the user against the bill rows."""
    by_key = {r["key"]: r for r in rows}
    out = []
    for s in sent or []:
        amt = _D(s.get("amount"))
        if amt <= 0:
            continue
        key = s.get("key")
        if not key:
            if s.get("pbItemId"):
                key = f"i:{int(s['pbItemId'])}"
            elif s.get("gstType"):
                key = f"g:{_gst_plain(s['gstType'])}"
            elif s.get("jeLineId"):
                key = f"j:{int(s['jeLineId'])}"
        row = by_key.get(key)
        if not row:
            raise ValueError(f"Row {s.get('ccCode') or key} is not on this bill")
        if amt > _D(row["balanceAmount"]):
            raise ValueError(f"{row['ccCode'] or row['description']}: amount {amt} exceeds row balance "
                             f"{_D(row['balanceAmount'])}")
        out.append({**row, "amount": float(amt)})
    return out


def insert_adjustment(pr, link_type, bill, je, lines, adj_date, user_id, remarks=None):
    """Write one adjustment + its lines and post it (caller validated, caller commits)."""
    from app.modules.finance.accounting.posting_engine import post_document, PostingError
    amount = _D(sum(_D(l["amount"]) for l in lines))
    a = AdvanceAdjustmentMaster(
        adjustment_no=_generate_no(), adjustment_date=adj_date,
        project_code=pr.project_code, vendor_id=pr.vendor_id, payment_request_id=pr.id,
        link_type=link_type,
        purchase_bill_id=bill.id if bill else None, brr_id=bill.brr_id if bill else None,
        journal_id=je.id if je else None, bill_no=bill.purchase_bill_no if bill else je.voucher_no,
        amount=amount, remarks=(remarks or None),
        workflow_status=_ACTIVE, created_by=_uid(user_id), created_at=datetime.utcnow(),
    )
    db.session.add(a)
    db.session.flush()
    for idx, l in enumerate(lines, start=1):
        db.session.add(AdvanceAdjustmentLine(
            adjustment_id=a.id, sl_no=idx, line_type=l["lineType"], pb_item_id=l["pbItemId"],
            gst_type=l["gstType"], je_line_id=l["jeLineId"], cc_code=l["ccCode"], cc_name=l["ccName"],
            description=l["description"], booked_amount=_D(l["bookedAmount"]), amount=_D(l["amount"]),
        ))
    db.session.flush()
    try:
        post_document(SOURCE_TYPE, a.id, _uid(user_id))
    except PostingError as e:
        raise ValueError(f"Ledger posting failed: {e}")
    db.session.flush()
    return a


def create_adjustment(data, user_id):
    """POST {paymentRequestId, purchaseBillId | journalId, amount, rows?:[{key, amount}],
    adjustmentDate?, remarks?}. Without rows the amount is split row by row."""
    try:
        pr = _get_advance_request(data.get("paymentRequestId"), for_update=True)
        if pr.workflow_status != "Approved":
            return res(f"Advance request {pr.pr_no} is not Approved", [], 400)
        if not _can_adjust(pr, user_id):
            return res("You are not allowed to adjust this advance", [], 403)
        link_type, bill, je = _resolve_bill(pr, data, for_update=True)
        if link_type == JOURNAL and not _journal_allowed(pr.project_code, user_id, "EDIT"):
            raise _Forbidden("You do not have permission for journal entries")
        lock = locked_type(pr)
        if lock and lock != link_type:
            return res(f"Advance {pr.pr_no} is already adjusted against {lock} bills — "
                       f"one type per advance", [], 400)

        adj_date = parse_date(data.get("adjustmentDate"), "adjustmentDate") if data.get("adjustmentDate") \
            else date.today()
        fy = _fy_locked(adj_date)
        if fy:
            return res(f"Financial year {fy.fy_code} is locked", [], 400)

        rows, open_bal, room = bill_caps(pr, link_type, bill, je)
        available = available_advance(pr)
        if data.get("rows"):
            lines = _build_lines(rows, data["rows"])
            amount = _D(sum(l["amount"] for l in lines))
            if data.get("amount") not in (None, "") and _D(data["amount"]) != amount:
                return res(f"Row total {amount} does not match amount {_D(data['amount'])}", [], 400)
        else:
            amount = _D(data.get("amount"))
            lines = [r for r in fill_rows(rows, amount) if r["amount"] > 0]
            if _D(sum(l["amount"] for l in lines)) != amount:
                return res(f"Amount {amount} is more than this bill's rows can take "
                           f"({_D(sum(r['balanceAmount'] for r in rows))})", [], 400)
        bill_no = bill.purchase_bill_no if bill else je.voucher_no
        if amount <= 0:
            return res("Adjustment amount must be greater than 0", [], 400)
        if amount > available:
            return res(f"Amount {amount} exceeds the outstanding advance {available} of {pr.pr_no}", [], 400)
        if amount > open_bal:
            return res(f"Amount {amount} exceeds the open balance {open_bal} of {bill_no}", [], 400)
        if room is not None and amount > room:
            src = f"BRR {bill.brr_no}" if bill else f"journal {bill_no}"
            return res(f"Amount {amount} exceeds what is left to request on {src} ({room}) — "
                       f"other Payment Requests already cover it", [], 400)

        a = insert_adjustment(pr, link_type, bill, je, lines, adj_date, user_id, data.get("remarks"))
        db.session.commit()
        return res(f"Advance {amount} of {pr.pr_no} adjusted against {bill_no}", adjustment_payload(a), 201)
    except _Forbidden as e:
        return _err(e, 403)
    except LookupError as e:
        return _err(e, 404)
    except ValueError as e:
        return _err(e, 400)
    except Exception as e:
        return _err(e, 500)


def cancel_adjustment(adj_id, data, user_id):
    """Cancel: reverse the posting (-REV), keep the record as Cancelled. The
    amount goes back to the advance's outstanding and the bill's balance."""
    from app.modules.finance.accounting.posting_engine import active_posting, reverse_posting
    try:
        a = AdvanceAdjustmentMaster.query.filter(AdvanceAdjustmentMaster.id == adj_id).with_for_update().first()
        if not a:
            return res("Advance adjustment not found", [], 404)
        if a.workflow_status == "Cancelled":
            return res(f"{a.adjustment_no} is already cancelled", [], 400)
        pr = a.payment_request
        if not (_is_super_admin(user_id) or a.created_by == _uid(user_id) or _can_adjust(pr, user_id)):
            return res("You are not allowed to cancel this adjustment", [], 403)
        if a.link_type == JOURNAL and not _journal_allowed(a.project_code, user_id, "EDIT"):
            return res("You do not have permission for journal entries", [], 403)
        led = active_posting(SOURCE_TYPE, a.id)
        fy = getattr(led, "financial_year", None) if led else None
        if fy is not None and fy.is_locked:
            return res(f"Financial year {fy.fy_code} is locked", [], 400)
        reason = (data or {}).get("reason") or None
        reverse_posting(SOURCE_TYPE, a.id, _uid(user_id),
                        remarks=f"Advance adjustment {a.adjustment_no} cancelled" + (f": {reason}" if reason else ""))
        a.workflow_status = "Cancelled"
        a.cancelled_by = _uid(user_id)
        a.cancelled_at = datetime.utcnow()
        a.cancel_reason = reason
        db.session.commit()
        return res(f"{a.adjustment_no} cancelled", adjustment_payload(a), 200)
    except Exception as e:
        return _err(e, 500)


# ══════════════════════════════════════════════════════════════════
# GUARD used by Account › Payment: an advance payment whose money is
# already adjusted can't be rebacked / rejected / cancelled.
# ══════════════════════════════════════════════════════════════════

def advance_payment_release_error(receipt):
    """Message when taking this approved advance payment out would leave the
    request adjusted for more than is paid; else None."""
    if (receipt.payment_type or "") != "advance" or receipt.workflow_status != "Approved":
        return None
    pr_id = receipt.payment_request_id
    if not pr_id:
        return None
    paid_after = advance_paid_approved(pr_id) - _D(receipt.total_invoice_amount)
    adjusted = adjusted_on_request(pr_id)
    if adjusted > paid_after:
        return (f"{adjusted} of this advance is adjusted against bills — cancel those adjustments "
                f"first (only {max(paid_after, Decimal('0.00'))} would remain paid)")
    return None


# ══════════════════════════════════════════════════════════════════
# ONE-TIME CONVERSION of the old "link the advance to one bill" model
#   (PaymentRequestMaster.link_type / brr_id / journal_id on an ADVANCE)
#   → Advance Adjustments. Run: python scripts/convert_advance_links.py
# ══════════════════════════════════════════════════════════════════

def _legacy_saved_split(pr):
    """Amounts the old CC split saved on the advance payments, per row key
    ("i:<pb item>", "g:<bill>:<IGST>", "j:<je line>")."""
    out = {}
    for r in BillPaymentReceiptMaster.query.filter(
            BillPaymentReceiptMaster.payment_request_id == pr.id,
            BillPaymentReceiptMaster.payment_type == "advance",
            BillPaymentReceiptMaster.workflow_status == "Approved").all():
        for i in r.items:
            key = f"i:{i.pb_item_id}" if i.pb_item_id else (f"j:{i.je_line_id}" if i.je_line_id else None)
            if key:
                out[key] = out.get(key, 0.0) + float(i.current_amount or 0)
        for g in r.gst_lines:
            if g.is_selected and ":" in (g.gst_type or ""):
                bid, kind = g.gst_type.split(":", 1)
                out[f"g:{bid}:{kind}"] = out.get(f"g:{bid}:{kind}", 0.0) + float(g.current_amount or 0)
    return out


def convert_legacy_links(user_id=None, apply=False):
    """Turn every LINKED advance request into adjustments against its bill(s):
    the old saved CC split is kept where there was one, the rest is filled
    row by row (oldest bill first). Advance payments are re-posted untagged
    (-REV + new posting) because the adjustment now carries the CC tags.
    Returns a report list; writes only when apply=True."""
    from app.modules.finance.accounting.posting_engine import active_posting, reverse_posting, post_document
    report = []
    prs = PaymentRequestMaster.query.filter(
        PaymentRequestMaster.source_type == "ADVANCE",
        PaymentRequestMaster.link_type.isnot(None)).order_by(PaymentRequestMaster.id.asc()).all()
    for pr in prs:
        sp = db.session.begin_nested()
        item = {"prNo": pr.pr_no, "linkType": pr.link_type, "adjustments": [], "error": None}
        try:
            saved = _legacy_saved_split(pr)
            left = available_advance(pr)
            targets = []
            if pr.link_type == BRR and pr.brr_id:
                targets = [(BRR, b, None) for b in PurchaseBillMaster.query.filter(
                    PurchaseBillMaster.brr_id == pr.brr_id,
                    PurchaseBillMaster.workflow_status == "Approved").order_by(PurchaseBillMaster.id.asc()).all()]
            elif pr.link_type == JOURNAL and pr.journal_id:
                je = JournalEntryMaster.query.get(pr.journal_id)
                targets = [(JOURNAL, None, je)] if je else []
            # clear the old link first so the request stops counting as "requested"
            pr.link_type = pr.linked_at = pr.linked_by = None
            pr.brr_id = pr.journal_id = None
            pr.brr_no = pr.journal_voucher_no = None
            pr.journal_date = pr.party_date = None
            pr.order_category = pr.party_bill_no = None
            pr.bill_amount = pr.previously_requested = Decimal("0.00")
            db.session.flush()
            # advance payments: drop the old split rows, re-post untagged
            for r in BillPaymentReceiptMaster.query.filter(
                    BillPaymentReceiptMaster.payment_request_id == pr.id,
                    BillPaymentReceiptMaster.payment_type == "advance").all():
                BillPaymentReceiptItem.query.filter_by(receipt_id=r.id).delete()
                BillPaymentReceiptGst.query.filter_by(receipt_id=r.id).delete()
                db.session.flush()
                if r.workflow_status == "Approved" and active_posting("bill_payment", r.id, for_update=True):
                    reverse_posting("bill_payment", r.id, user_id,
                                    remarks=f"Advance {pr.pr_no}: CC tags move to Advance Adjustments")
                    db.session.flush()
                    post_document("bill_payment", r.id, user_id)
                    db.session.flush()
            for link_type, bill, je in targets:
                if left <= 0:
                    break
                rows, open_bal, room = bill_caps(pr, link_type, bill, je)
                cap = min([left, open_bal] + ([room] if room is not None else []))
                if cap <= 0:
                    continue
                # saved split first, then fill
                lines, need = [], cap
                for r in rows:
                    key = r["key"] if r["lineType"] != "gst" else f"g:{bill.id}:{r['gstType']}"
                    take = _D(min(saved.get(key, 0.0), r["balanceAmount"], float(need)))
                    if take > 0:
                        r["balanceAmount"] = round(r["balanceAmount"] - float(take), 2)
                        r["amount"] = float(take)
                        need -= take
                fill_extra = [dict(r, amount=0.0) for r in rows]
                fill_rows(fill_extra, need)
                for r, extra in zip(rows, fill_extra):
                    total = round(float(r.get("amount") or 0) + float(extra["amount"]), 2)
                    if total > 0:
                        lines.append(dict(r, amount=total))
                if not lines:
                    continue
                a = insert_adjustment(pr, link_type, bill, je, lines, date.today(), user_id,
                                      remarks="Converted from the old advance link")
                left -= _D(a.amount)
                item["adjustments"].append({"adjustmentNo": a.adjustment_no, "billNo": a.bill_no,
                                            "amount": float(a.amount)})
            item["outstandingAfter"] = float(left)
            sp.commit()
        except Exception as e:
            sp.rollback()
            item["error"] = str(e)
        report.append(item)
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return report


# ══════════════════════════════════════════════════════════════════
# BILL-WISE VIEW of an advance (Account › Payment advance page): the bill
# rows its active adjustments sit on, in the Bill / Voucher breakdown shape.
#   currentAmount = adjusted by THIS advance
#   advanceAmount = adjusted by other advances
#   balanceAmount = row balance before this advance (UI shows balance − current)
# ══════════════════════════════════════════════════════════════════

def advance_breakdown_rows(pr):
    """(link_type, items, gst_lines) for the advance's active adjustments."""
    adjs = (AdvanceAdjustmentMaster.query
            .filter_by(payment_request_id=pr.id, workflow_status=_ACTIVE)
            .order_by(AdvanceAdjustmentMaster.id.asc()).all())
    mine, order = {}, []          # (bill key) → {row key: amount}
    for a in adjs:
        bkey = ("BRR", a.purchase_bill_id) if a.link_type == BRR else ("JOURNAL", a.journal_id)
        if bkey not in mine:
            mine[bkey] = {}
            order.append(bkey)
        for l in a.lines:
            k = (f"i:{l.pb_item_id}" if l.line_type == "item" else
                 f"g:{_gst_plain(l.gst_type)}" if l.line_type == "gst" else f"j:{l.je_line_id}")
            mine[bkey][k] = mine[bkey].get(k, 0.0) + float(l.amount or 0)
    items, gst_lines = [], []
    for kind, bid in order:
        amounts = mine[(kind, bid)]
        if kind == "BRR":
            bill = PurchaseBillMaster.query.get(bid)
            if not bill:
                continue
            head = {"purchaseBillId": bill.id, "purchaseBillNo": bill.purchase_bill_no, "orderNo": _order_no(bill),
                    "brrNo": bill.brr_no, "brrDate": _fmt(getattr(bill, "brr_date", None))}
            rows = purchase_bill_rows(bill)
        else:
            je = JournalEntryMaster.query.get(bid)
            if not je:
                continue
            head = {"journalEntryId": je.id, "voucherNo": je.voucher_no, "entryDate": _fmt(je.entry_date)}
            rows = journal_rows(je)
        for r in rows:
            cur = round(amounts.get(r["key"], 0.0), 2)
            if cur <= 0:
                continue
            row = {**head,
                   "pbItemId": r["pbItemId"], "jeLineId": r["jeLineId"], "slNo": r["slNo"],
                   "ccCode": r["ccCode"] or "", "ccName": r["ccName"] or "", "description": r["description"] or "",
                   "bookedAmount": r["bookedAmount"], "paidAmount": r["paidAmount"],
                   "advanceAmount": round(r["adjustedAmount"] - cur, 2),
                   "balanceAmount": round(r["balanceAmount"] + cur, 2),
                   "currentAmount": cur}
            if r["lineType"] == "gst":
                gst_lines.append({**row, "gstType": f"{bid}:{r['gstType']}", "isSelected": True, "percent": 0})
            else:
                items.append(row)
    link_type = adjs[0].link_type if adjs else None
    return link_type, items, gst_lines
