from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.billPaymentReceipt import (
    BillPaymentReceiptMaster,
    BillPaymentReceiptItem,
    BillPaymentReceiptGst,
)
from app.models.purchaseBill import PurchaseBillMaster, PurchaseBillItem
from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.journalVoucher import PettyCashJournalVoucher
from app.response import res
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
from app.models.user import User
from app.modules.communication import whatsapp_events as wa

_MODULE = "payment"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _generate_receipt_no():
    last = (
        db.session.query(BillPaymentReceiptMaster.receipt_no)
        .order_by(BillPaymentReceiptMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0]:
        raw = last[0]
        try:
            num = int(raw[3:]) if raw.startswith("BPR") else int(raw)
        except Exception:
            num = 0
    return f"BPR{str(num + 1).zfill(3)}"


def _paid_item_map(purchase_bill_id, exclude_id=None):
    """Sum current_amount per pb_item_id from ALL Approved receipts for a purchase bill.
    Looks at items directly so multi-bill payments (where purchase_bill_id is the first bill)
    are correctly accounted for across all bills."""
    pb_item_ids = [
        row.id for row in
        PurchaseBillItem.query.filter_by(purchase_bill_id=purchase_bill_id)
        .with_entities(PurchaseBillItem.id).all()
    ]
    if not pb_item_ids:
        return {}
    q = (
        db.session.query(
            BillPaymentReceiptItem.pb_item_id,
            func.coalesce(func.sum(BillPaymentReceiptItem.current_amount), 0).label("paid"),
        )
        .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptItem.receipt_id)
        .filter(
            BillPaymentReceiptItem.pb_item_id.in_(pb_item_ids),
            BillPaymentReceiptMaster.workflow_status == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_id)
    return {r.pb_item_id: float(r.paid) for r in q.group_by(BillPaymentReceiptItem.pb_item_id).all()}


def _paid_gst_map(purchase_bill_id, exclude_id=None):
    """Sum current_amount per gst_type from ALL Approved receipts for a purchase bill.
    Handles both single-bill (plain 'IGST') and multi-bill ('{bill_id}:IGST') gst_type formats."""
    prefix = f"{purchase_bill_id}:"
    q = (
        db.session.query(
            BillPaymentReceiptGst.gst_type,
            func.coalesce(func.sum(BillPaymentReceiptGst.current_amount), 0).label("paid"),
        )
        .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptGst.receipt_id)
        .filter(
            db.or_(
                db.and_(
                    BillPaymentReceiptMaster.purchase_bill_id == purchase_bill_id,
                    ~BillPaymentReceiptGst.gst_type.contains(":"),
                ),
                BillPaymentReceiptGst.gst_type.startswith(prefix),
            ),
            BillPaymentReceiptMaster.workflow_status == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_id)
    result = {}
    for r in q.group_by(BillPaymentReceiptGst.gst_type).all():
        key = r.gst_type.split(":", 1)[1] if ":" in r.gst_type else r.gst_type
        result[key] = result.get(key, 0) + float(r.paid)
    return result


def _build_detail_payload(r):
    is_voucher = (r.payment_type or "bill") == "voucher"

    if is_voucher:
        return _build_voucher_detail_payload(r)

    # ── BILL PAYMENT ─────────────────────────────────────────────
    # Batch-load PurchaseBillItem → PurchaseBillMaster for per-item bill info
    pb_item_ids = [i.pb_item_id for i in r.items if i.pb_item_id]
    pbi_by_id = {}
    bills_by_id = {}
    if pb_item_ids:
        pbi_rows = PurchaseBillItem.query.filter(PurchaseBillItem.id.in_(pb_item_ids)).all()
        pbi_by_id = {p.id: p for p in pbi_rows}
        bill_ids = list({p.purchase_bill_id for p in pbi_rows})
        bill_rows = PurchaseBillMaster.query.filter(PurchaseBillMaster.id.in_(bill_ids)).all()
        bills_by_id = {b.id: b for b in bill_rows}

    # Pre-compute paid maps per unique bill
    unique_bill_ids = list(bills_by_id.keys()) or ([r.purchase_bill_id] if r.purchase_bill_id else [])
    paid_basic_by_bill = {bid: _paid_item_map(bid, exclude_id=r.id) for bid in unique_bill_ids}
    paid_gst_by_bill   = {bid: _paid_gst_map(bid,  exclude_id=r.id) for bid in unique_bill_ids}

    def _bill_order_no(b):
        if not b or not b.brr:
            return None
        return (b.brr.order.order_no if b.brr.order else None) or (b.brr.pw_order.order_no if b.brr.pw_order else None)

    items = []
    for i in r.items:
        booked   = float(i.booked_amount  or 0)
        current  = float(i.current_amount or 0)
        pbi      = pbi_by_id.get(i.pb_item_id)
        bill     = bills_by_id.get(pbi.purchase_bill_id) if pbi else None
        bill_id  = bill.id if bill else r.purchase_bill_id
        paid     = paid_basic_by_bill.get(bill_id, {}).get(i.pb_item_id, 0)
        items.append({
            "id":              i.id,
            "pbItemId":        i.pb_item_id,
            "purchaseBillId":  bill_id,
            "purchaseBillNo":  bill.purchase_bill_no if bill else None,
            "brrNo":           bill.brr_no           if bill else None,
            "brrDate":         _fmt_date(bill.brr_date) if bill else None,
            "orderNo":         _bill_order_no(bill),
            "slNo":            i.sl_no,
            "ccCode":          i.cc_code,
            "ccName":          i.cc_name,
            "description":     pbi.description if pbi else None,
            "bookedAmount":    booked,
            "paidAmount":      paid,
            "balanceAmount":   max(booked - paid, 0),
            "currentAmount":   current,
        })

    gst_lines = []
    for g in r.gst_lines:
        booked  = float(g.booked_amount  or 0)
        current = float(g.current_amount or 0)
        # Parse bill prefix from gst_type for multi-bill records
        if ":" in (g.gst_type or ""):
            raw_bill_id, gst_type_key = g.gst_type.split(":", 1)
            try:
                gst_bill_id = int(raw_bill_id)
            except ValueError:
                gst_bill_id = r.purchase_bill_id
                gst_type_key = g.gst_type
        else:
            gst_bill_id  = r.purchase_bill_id
            gst_type_key = g.gst_type
        bill = bills_by_id.get(gst_bill_id)
        paid = paid_gst_by_bill.get(gst_bill_id, {}).get(gst_type_key, 0)
        gst_lines.append({
            "id":             g.id,
            "gstType":        gst_type_key,
            "purchaseBillId": gst_bill_id,
            "purchaseBillNo": bill.purchase_bill_no if bill else None,
            "orderNo":        _bill_order_no(bill),
            "brrNo":          bill.brr_no if bill else None,
            "brrDate":        _fmt_date(bill.brr_date) if bill else None,
            "ccCode":         g.cc_code,
            "ccName":         g.cc_name,
            "percent":        float(g.percent or 0) if hasattr(g, "percent") else 0,
            "bookedAmount":   booked,
            "paidAmount":     paid,
            "balanceAmount":  max(booked - paid, 0),
            "currentAmount":  current,
            "isSelected":     g.is_selected,
        })

    # Per-bill summary (for multi-bill display)
    bills_summary = []
    for bid in unique_bill_ids:
        b = bills_by_id.get(bid)
        if b:
            bills_summary.append({
                "id":             b.id,
                "purchaseBillNo": b.purchase_bill_no,
                "brrNo":          b.brr_no,
                "brrDate":        _fmt_date(b.brr_date),
                "orderNo":        _bill_order_no(b),
            })

    primary_bill = r.purchase_bill
    return {
        "id":                  r.id,
        "receiptNo":           r.receipt_no,
        "receiptUuid":         r.receipt_uuid,
        "paymentType":         r.payment_type or "bill",
        "paymentDate":         _fmt_date(r.payment_date),
        "purchaseBillId":      r.purchase_bill_id,
        "purchaseBillNo":      primary_bill.purchase_bill_no if primary_bill else None,
        "brrNo":               primary_bill.brr_no           if primary_bill else None,
        "brrDate":             _fmt_date(primary_bill.brr_date) if primary_bill else None,
        "bvsDate":             _fmt_date(r.bvs_date),
        "vendorBillNo":        r.vendor_bill_no,
        "vendorBillDate":      _fmt_date(r.vendor_bill_date),
        "orderNo":             r.order_no,
        "projectCode":         r.project_code,
        "vendorId":            r.vendor_id,
        "vendorName":          r.vendor.ledger_name if r.vendor else None,
        "paymentMode":         r.payment_mode,
        "cashAcId":            r.cash_ac_id,
        "cashAcName":          r.cash_account.bank_holder_name    if r.cash_account else None,
        "cashAcNo":            r.cash_account.bank_account_number if r.cash_account else None,
        "bankAcId":            r.bank_ac_id,
        "bankAcName":          r.bank_account.bank_holder_name    if r.bank_account else None,
        "bankAcNo":            r.bank_account.bank_account_number if r.bank_account else None,
        "utrVoucherNo":        r.utr_voucher_no,
        "paymentRemarks":      r.payment_remarks,
        "basicAmount":         float(r.basic_amount         or 0),
        "gstAmount":           float(r.gst_amount           or 0),
        "discount":            float(r.discount             or 0),
        "roundOff":            float(r.round_off            or 0),
        "totalInvoiceAmount":  float(r.total_invoice_amount or 0),
        "workflowStatus":      r.workflow_status,
        "currentLevel":        r.current_level,
        "locked":              r.locked,
        "createdBy":           r.creator.username   if r.creator   else None,
        "createdAt":           _fmt_date(r.created_at),
        "submittedBy":         r.submitter.username if r.submitter else None,
        "submittedAt":         _fmt_date(r.submitted_at),
        "approvedBy":          r.approver.username  if r.approver  else None,
        "finalApprovedAt":     _fmt_date(r.final_approved_at),
        "rejectedBy":          r.rejector.username  if r.rejector  else None,
        "rejectedAt":          _fmt_date(r.rejected_at),
        "bills":               bills_summary,
        "items":               items,
        "gstLines":            gst_lines,
    }


def _build_voucher_detail_payload(r):
    """Build detail payload for voucher-type payment receipts."""
    je = r.journal_entry

    # Collect unique JE IDs from items
    je_line_ids = [i.je_line_id for i in r.items if i.je_line_id]
    je_line_by_id = {}
    je_by_id = {}
    if je_line_ids:
        lines = JournalEntryLine.query.filter(JournalEntryLine.id.in_(je_line_ids)).all()
        je_line_by_id = {l.id: l for l in lines}
        je_ids = list({l.journal_id for l in lines})
        entries = JournalEntryMaster.query.filter(JournalEntryMaster.id.in_(je_ids)).all()
        je_by_id = {e.id: e for e in entries}

    # Pre-compute paid maps and docket description maps per unique JE
    unique_je_ids = list(je_by_id.keys()) or ([r.journal_entry_id] if r.journal_entry_id else [])
    paid_by_je = {jid: _paid_je_line_map(jid, exclude_id=r.id) for jid in unique_je_ids}
    desc_by_je = {
        jid: _docket_desc_map(jid)
        for jid, e in je_by_id.items()
        if e.entry_mode == "bulk_docket"
    }

    items = []
    for i in r.items:
        booked  = float(i.booked_amount  or 0)
        current = float(i.current_amount or 0)
        jel     = je_line_by_id.get(i.je_line_id)
        entry   = je_by_id.get(jel.journal_id) if jel else None
        je_id   = entry.id if entry else r.journal_entry_id
        paid    = paid_by_je.get(je_id, {}).get(i.je_line_id, 0)
        items.append({
            "id":              i.id,
            "jeLineId":        i.je_line_id,
            "journalEntryId":  je_id,
            "voucherNo":       entry.voucher_no if entry else (je.voucher_no if je else None),
            "entryDate":       _fmt_date(entry.entry_date) if entry else None,
            "slNo":            i.sl_no,
            "ccCode":          i.cc_code,
            "ccName":          i.cc_name,
            "description":     desc_by_je.get(je_id, {}).get(i.cc_code or "", ""),
            "bookedAmount":    booked,
            "paidAmount":      paid,
            "balanceAmount":   max(booked - paid, 0),
            "currentAmount":   current,
        })

    entries_summary = []
    for jid in unique_je_ids:
        e = je_by_id.get(jid)
        if e:
            entries_summary.append({
                "id":        e.id,
                "voucherNo": e.voucher_no,
                "entryDate": _fmt_date(e.entry_date),
            })

    return {
        "id":                  r.id,
        "receiptNo":           r.receipt_no,
        "receiptUuid":         r.receipt_uuid,
        "paymentType":         "voucher",
        "paymentDate":         _fmt_date(r.payment_date),
        "journalEntryId":      r.journal_entry_id,
        "voucherNo":           je.voucher_no if je else None,
        "projectCode":         r.project_code,
        "vendorId":            r.vendor_id,
        "vendorName":          r.vendor.ledger_name if r.vendor else None,
        "paymentMode":         r.payment_mode,
        "cashAcId":            r.cash_ac_id,
        "cashAcName":          r.cash_account.bank_holder_name    if r.cash_account else None,
        "cashAcNo":            r.cash_account.bank_account_number if r.cash_account else None,
        "bankAcId":            r.bank_ac_id,
        "bankAcName":          r.bank_account.bank_holder_name    if r.bank_account else None,
        "bankAcNo":            r.bank_account.bank_account_number if r.bank_account else None,
        "utrVoucherNo":        r.utr_voucher_no,
        "paymentRemarks":      r.payment_remarks,
        "basicAmount":         float(r.basic_amount         or 0),
        "gstAmount":           0,
        "discount":            float(r.discount             or 0),
        "roundOff":            float(r.round_off            or 0),
        "totalInvoiceAmount":  float(r.total_invoice_amount or 0),
        "workflowStatus":      r.workflow_status,
        "currentLevel":        r.current_level,
        "locked":              r.locked,
        "createdBy":           r.creator.username   if r.creator   else None,
        "createdAt":           _fmt_date(r.created_at),
        "submittedBy":         r.submitter.username if r.submitter else None,
        "submittedAt":         _fmt_date(r.submitted_at),
        "approvedBy":          r.approver.username  if r.approver  else None,
        "finalApprovedAt":     _fmt_date(r.final_approved_at),
        "rejectedBy":          r.rejector.username  if r.rejector  else None,
        "rejectedAt":          _fmt_date(r.rejected_at),
        "entries":             entries_summary,
        "items":               items,
        "gstLines":            [],
    }


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Approved Purchase Bills for BVS dropdown
# ══════════════════════════════════════════════════════════════════

def get_approved_purchase_bills(data):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        query = PurchaseBillMaster.query.filter(
            PurchaseBillMaster.project_code    == project_code,
            PurchaseBillMaster.workflow_status == "Approved",
        )

        if data.get("vendorId"):
            query = query.filter(PurchaseBillMaster.vendor_id == int(data.get("vendorId")))

        rows = query.order_by(PurchaseBillMaster.id.desc()).all()

        # For each bill: sum paid from Approved receipts, check for active (non-rejected) receipt
        bill_ids = [r.id for r in rows]
        paid_map = {}
        in_progress_map = {}
        locked_map = {}
        if bill_ids:
            paid_q = (
                db.session.query(
                    BillPaymentReceiptMaster.purchase_bill_id,
                    func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0).label("paid"),
                )
                .filter(
                    BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids),
                    BillPaymentReceiptMaster.workflow_status == "Approved",
                )
                .group_by(BillPaymentReceiptMaster.purchase_bill_id)
                .all()
            )
            paid_map = {row.purchase_bill_id: float(row.paid) for row in paid_q}

            # Sum Draft/Reback/Pending amounts only (not Approved/Rejected)
            inprog_q = (
                db.session.query(
                    BillPaymentReceiptMaster.purchase_bill_id,
                    func.coalesce(func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0).label("inprog"),
                )
                .filter(
                    BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids),
                    BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
                )
                .group_by(BillPaymentReceiptMaster.purchase_bill_id)
                .all()
            )
            in_progress_map = {row.purchase_bill_id: float(row.inprog) for row in inprog_q}
            # Note: paid_map already covers Approved amounts, so balance = booked - paid - in_progress

            # Only Draft/Reback/Pending lock the bill — Approved/Rejected are terminal
            active_q = (
                db.session.query(
                    BillPaymentReceiptMaster.purchase_bill_id,
                    BillPaymentReceiptMaster.workflow_status,
                )
                .filter(
                    BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids),
                    BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
                )
                .order_by(BillPaymentReceiptMaster.id.desc())
                .all()
            )
            locked_map = {}
            for row in active_q:
                if row.purchase_bill_id not in locked_map:
                    locked_map[row.purchase_bill_id] = row.workflow_status

        result = []
        for r in rows:
            booked     = float(r.total_invoice_amount or 0)
            paid       = paid_map.get(r.id, 0)
            in_prog    = in_progress_map.get(r.id, 0)
            # True balance = booked - approved - in-progress drafts
            balance    = max(booked - paid - in_prog, 0)
            is_locked  = r.id in locked_map
            result.append({
                "id":            r.id,
                "purchaseBillNo": r.purchase_bill_no,
                "processingDate": _fmt_date(r.processing_date),
                "vendorId":       r.vendor_id,
                "vendorBillNo":   r.vendor_bill_no,
                "vendorBillDate": _fmt_date(r.vendor_bill_date),
                "brrNo":          r.brr_no,
                "brrDate":        _fmt_date(r.brr_date),
                "orderNo":        (
                    (r.brr.order.order_no    if r.brr and r.brr.order    else None) or
                    (r.brr.pw_order.order_no if r.brr and r.brr.pw_order else None)
                ),
                "bookedAmount":      booked,
                "approvedPaidAmount": paid,
                "inProgressAmount":   in_prog,
                "balanceAmount":      balance,
                "isLocked":           is_locked,
                "paymentStatus":      locked_map.get(r.id),
            })

        return res("Approved purchase bills fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Items + GST of a purchase bill with paid/balance
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_payment_items(bill_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if bill.workflow_status != "Approved":
            return res("Only Approved purchase bills can be paid", [], 400)

        paid_basic = _paid_item_map(bill.id)
        paid_gst   = _paid_gst_map(bill.id)

        items = []
        for i in bill.items:
            booked  = float(i.basic_amount or 0)
            paid    = paid_basic.get(i.id, 0)
            balance = max(booked - paid, 0)
            items.append({
                "pbItemId":      i.id,
                "slNo":          i.sl_no,
                "ccCode":        i.cc_code,
                "ccName":        i.cc_name,
                "description":   i.description,
                "bookedAmount":  booked,
                "paidAmount":    paid,
                "balanceAmount": balance,
                "currentAmount": 0,
            })

        order_no = (
            (bill.brr.order.order_no    if bill.brr and bill.brr.order    else None) or
            (bill.brr.pw_order.order_no if bill.brr and bill.brr.pw_order else None)
        )

        gst_lines = []
        for g in bill.gst_lines:
            booked  = float(g.gst_amount or 0)
            paid    = paid_gst.get(g.gst_type, 0)
            balance = max(booked - paid, 0)
            gst_lines.append({
                "gstType":        g.gst_type,
                "purchaseBillId": bill.id,
                "purchaseBillNo": bill.purchase_bill_no,
                "orderNo":        order_no,
                "brrNo":          bill.brr_no,
                "brrDate":        _fmt_date(bill.brr_date),
                "ccCode":         g.cc_code,
                "ccName":         g.cc_name,
                "percent":        float(g.percent or 0),
                "bookedAmount":   booked,
                "paidAmount":     paid,
                "balanceAmount":  balance,
                "currentAmount":  0,
                "isSelected":     g.is_selected,
            })

        return res("Purchase bill payment items fetched", {
            "purchaseBillId":      bill.id,
            "purchaseBillNo":      bill.purchase_bill_no,
            "bvsDate":             _fmt_date(bill.processing_date),
            "vendorBillNo":        bill.vendor_bill_no,
            "vendorBillDate":      _fmt_date(bill.vendor_bill_date),
            "brrNo":               bill.brr_no,
            "brrDate":             _fmt_date(bill.brr_date),
            "orderNo":             order_no,
            "vendorId":            bill.vendor_id,
            "vendorName":          bill.vendor.ledger_name if bill.vendor else None,
            "totalBookedBasic":    float(bill.basic_amount         or 0),
            "totalBookedGst":      float(bill.gst_amount           or 0),
            "totalBookedInvoice":  float(bill.total_invoice_amount or 0),
            "items":               items,
            "gstLines":            gst_lines,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Multi-bill items + GST with paid/balance
# ══════════════════════════════════════════════════════════════════

def get_purchase_bills_payment_items_multi(bill_ids):
    """Return combined items and GST for multiple purchase bills.
    GST types are prefixed with '{bill_id}:' so they remain distinct per bill."""
    try:
        if not bill_ids:
            return res("bill_ids required", [], 400)

        bills = PurchaseBillMaster.query.filter(
            PurchaseBillMaster.id.in_([int(b) for b in bill_ids])
        ).all()

        if not bills:
            return res("No purchase bills found", [], 404)

        invalid = [b for b in bills if b.workflow_status != "Approved"]
        if invalid:
            return res(
                f"Bills {[b.purchase_bill_no for b in invalid]} are not Approved",
                [], 400
            )

        all_items = []
        all_gst = []
        bills_meta = []

        for bill in bills:
            paid_basic = _paid_item_map(bill.id)
            paid_gst   = _paid_gst_map(bill.id)

            order_no = (
                (bill.brr.order.order_no    if bill.brr and bill.brr.order    else None) or
                (bill.brr.pw_order.order_no if bill.brr and bill.brr.pw_order else None)
            )

            for i in bill.items:
                booked  = float(i.basic_amount or 0)
                paid    = paid_basic.get(i.id, 0)
                balance = max(booked - paid, 0)
                all_items.append({
                    "pbItemId":        i.id,
                    "purchaseBillId":  bill.id,
                    "purchaseBillNo":  bill.purchase_bill_no,
                    "brrNo":           bill.brr_no,
                    "brrDate":         _fmt_date(bill.brr_date),
                    "orderNo":         order_no,
                    "slNo":            i.sl_no,
                    "ccCode":          i.cc_code,
                    "ccName":          i.cc_name,
                    "description":     i.description,
                    "bookedAmount":    booked,
                    "paidAmount":      paid,
                    "balanceAmount":   balance,
                    "currentAmount":   0,
                })

            for g in bill.gst_lines:
                booked  = float(g.gst_amount or 0)
                paid    = paid_gst.get(g.gst_type, 0)
                balance = max(booked - paid, 0)
                all_gst.append({
                    "gstType":        f"{bill.id}:{g.gst_type}",
                    "purchaseBillId": bill.id,
                    "purchaseBillNo": bill.purchase_bill_no,
                    "orderNo":        order_no,
                    "brrNo":          bill.brr_no,
                    "brrDate":        _fmt_date(bill.brr_date),
                    "ccCode":         g.cc_code,
                    "ccName":         g.cc_name,
                    "percent":        float(g.percent or 0),
                    "bookedAmount":   booked,
                    "paidAmount":     paid,
                    "balanceAmount":  balance,
                    "currentAmount":  0,
                    "isSelected":     g.is_selected,
                })

            bills_meta.append({
                "id":             bill.id,
                "purchaseBillNo": bill.purchase_bill_no,
                "brrNo":          bill.brr_no,
                "brrDate":        _fmt_date(bill.brr_date),
                "vendorBillNo":   bill.vendor_bill_no,
                "vendorBillDate": _fmt_date(bill.vendor_bill_date),
                "orderNo":        order_no,
                "vendorId":       bill.vendor_id,
                "vendorName":     bill.vendor.ledger_name if bill.vendor else None,
            })

        return res("Multi-bill payment items fetched", {
            "bills":    bills_meta,
            "items":    all_items,
            "gstLines": all_gst,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# VOUCHER PAYMENT HELPERS
# ══════════════════════════════════════════════════════════════════

def _paid_je_line_map(je_id, exclude_id=None, include_active=False):
    """Sum current_amount per je_line_id from Approved (and optionally active) receipts.

    include_active=True also counts Draft/Pending/Reback amounts so the picker shows
    true remaining balance when a receipt is already in-flight for this JE.
    """
    line_ids = [
        row.id for row in
        JournalEntryLine.query.filter_by(journal_id=je_id)
        .with_entities(JournalEntryLine.id).all()
    ]
    if not line_ids:
        return {}

    terminal_statuses = ["Rejected"]
    if include_active:
        status_filter = ~BillPaymentReceiptMaster.workflow_status.in_(terminal_statuses)
    else:
        status_filter = BillPaymentReceiptMaster.workflow_status == "Approved"

    q = (
        db.session.query(
            BillPaymentReceiptItem.je_line_id,
            func.coalesce(func.sum(BillPaymentReceiptItem.current_amount), 0).label("paid"),
        )
        .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptItem.receipt_id)
        .filter(
            BillPaymentReceiptItem.je_line_id.in_(line_ids),
            status_filter,
        )
    )
    if exclude_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_id)
    return {r.je_line_id: float(r.paid) for r in q.group_by(BillPaymentReceiptItem.je_line_id).all()}


def get_approved_journal_vouchers(data):
    """List approved new_voucher/bulk_docket journal entries for the voucher picker."""
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        query = (
            JournalEntryMaster.query
            .filter(
                JournalEntryMaster.project_code    == project_code,
                JournalEntryMaster.workflow_status == "Approved",
                JournalEntryMaster.entry_mode.in_(["new_voucher", "bulk_docket"]),
            )
        )

        vendor_id = data.get("vendorId")
        if vendor_id:
            # Match JEs that have a Cr line with this vendor_id, OR no Cr lines (single-entry)
            je_ids_with_cr_vendor = db.session.query(JournalEntryLine.journal_id).filter(
                JournalEntryLine.dr_cr == "Cr",
                JournalEntryLine.vendor_id == int(vendor_id),
            ).distinct().subquery()
            je_ids_no_cr = db.session.query(JournalEntryLine.journal_id).filter(
                JournalEntryLine.dr_cr == "Cr",
            ).distinct().subquery()
            query = query.filter(
                db.or_(
                    JournalEntryMaster.id.in_(je_ids_with_cr_vendor),
                    JournalEntryMaster.id.notin_(je_ids_no_cr),
                )
            )

        rows = query.order_by(JournalEntryMaster.id.desc()).all()

        result = []
        for je in rows:
            # include_active so balance reflects amounts locked in Draft/Pending receipts too
            paid_map = _paid_je_line_map(je.id, include_active=True)
            total_booked  = float(je.total_debit or 0)
            total_paid    = sum(paid_map.values())
            total_balance = max(total_booked - total_paid, 0)

            # Skip fully-paid JEs
            if total_balance == 0 and total_booked > 0:
                continue

            # Check active (Draft/Pending/Reback) receipts via primary journal_entry_id
            active_receipt = (
                BillPaymentReceiptMaster.query
                .filter(
                    BillPaymentReceiptMaster.journal_entry_id == je.id,
                    BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
                )
                .first()
            )

            # Also check secondary JEs: any active receipt whose items reference this JE's Dr lines
            if not active_receipt:
                dr_line_ids = [l.id for l in je.lines if l.dr_cr == "Dr" and l.account_type == "CC"]
                if dr_line_ids:
                    active_receipt_id_sq = (
                        db.session.query(BillPaymentReceiptItem.receipt_id)
                        .filter(BillPaymentReceiptItem.je_line_id.in_(dr_line_ids))
                        .subquery()
                    )
                    active_receipt = (
                        BillPaymentReceiptMaster.query
                        .filter(
                            BillPaymentReceiptMaster.id.in_(active_receipt_id_sq),
                            BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
                        )
                        .first()
                    )

            result.append({
                "id":            je.id,
                "voucherNo":     je.voucher_no,
                "entryDate":     _fmt_date(je.entry_date),
                "entryMode":     je.entry_mode,
                "totalDebit":    total_booked,
                "totalPaid":     total_paid,
                "balanceAmount": total_balance,
                "isLocked":      active_receipt is not None,
                "paymentStatus": active_receipt.workflow_status if active_receipt else None,
            })

        return res("Approved journal vouchers fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


def _docket_desc_map(je_id):
    """Build {cc_code: short_description} from docket lines linked to a bulk_docket JE.
    If multiple docket lines share the same cc_code, the last one wins (order by sl_no)."""
    desc_map = {}
    dockets = PettyCashJournalVoucher.query.filter_by(linked_journal_id=je_id).all()
    for docket in dockets:
        for dl in docket.lines:
            if dl.cc_code:
                desc_map[dl.cc_code] = dl.short_description or ""
    return desc_map


def get_journal_voucher_payment_items(je_id):
    """Return DR CC lines of a journal entry with paid/balance for voucher payment."""
    try:
        je = JournalEntryMaster.query.get(je_id)
        if not je:
            return res("Journal entry not found", [], 404)
        if je.workflow_status != "Approved":
            return res("Only Approved journal entries can be paid", [], 400)
        if je.entry_mode not in ("new_voucher", "bulk_docket"):
            return res("Only new_voucher and bulk_docket entries can be paid as vouchers", [], 400)

        paid_map = _paid_je_line_map(je.id)
        desc_map = _docket_desc_map(je.id) if je.entry_mode == "bulk_docket" else {}

        dr_lines = [l for l in je.lines if l.dr_cr == "Dr" and l.account_type == "CC"]
        items = []
        for idx, line in enumerate(dr_lines, start=1):
            booked  = float(line.debit_amount or 0)
            paid    = paid_map.get(line.id, 0)
            balance = max(booked - paid, 0)
            cc      = line.cc
            cc_code = cc.cc_code if cc else ""
            items.append({
                "jeLineId":     line.id,
                "slNo":         idx,
                "ccCode":       cc_code,
                "ccName":       cc.cc_name if cc else "",
                "description":  desc_map.get(cc_code, ""),
                "bookedAmount": booked,
                "paidAmount":   paid,
                "balanceAmount": balance,
                "currentAmount": 0,
            })

        # Cr line info (vendor or customer)
        cr_lines = [l for l in je.lines if l.dr_cr == "Cr"]
        cr_vendor_id   = cr_lines[0].vendor_id    if cr_lines else None
        cr_vendor_name = cr_lines[0].vendor.ledger_name if (cr_lines and cr_lines[0].vendor) else None
        cr_customer    = cr_lines[0].customer_ref  if cr_lines else None

        return res("Journal voucher payment items fetched", {
            "journalEntryId": je.id,
            "voucherNo":      je.voucher_no,
            "entryDate":      _fmt_date(je.entry_date),
            "entryMode":      je.entry_mode,
            "vendorId":       cr_vendor_id,
            "vendorName":     cr_vendor_name,
            "customerRef":    cr_customer,
            "totalDebit":     float(je.total_debit or 0),
            "items":          items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


def get_journal_vouchers_payment_items_multi(je_ids):
    """Return combined DR CC lines for multiple journal entries."""
    try:
        if not je_ids:
            return res("je_ids required", [], 400)

        entries = JournalEntryMaster.query.filter(
            JournalEntryMaster.id.in_([int(j) for j in je_ids])
        ).all()

        if not entries:
            return res("No journal entries found", [], 404)

        invalid = [e for e in entries if e.workflow_status != "Approved"]
        if invalid:
            return res(f"Entries {[e.voucher_no for e in invalid]} are not Approved", [], 400)

        invalid_mode = [e for e in entries if e.entry_mode not in ("new_voucher", "bulk_docket")]
        if invalid_mode:
            return res(f"Entries {[e.voucher_no for e in invalid_mode]} are not voucher type", [], 400)

        all_items = []
        entries_meta = []

        for je in entries:
            paid_map = _paid_je_line_map(je.id)
            desc_map = _docket_desc_map(je.id) if je.entry_mode == "bulk_docket" else {}
            dr_lines = [l for l in je.lines if l.dr_cr == "Dr" and l.account_type == "CC"]

            for idx, line in enumerate(dr_lines, start=1):
                booked  = float(line.debit_amount or 0)
                paid    = paid_map.get(line.id, 0)
                balance = max(booked - paid, 0)
                cc      = line.cc
                cc_code = cc.cc_code if cc else ""
                all_items.append({
                    "jeLineId":       line.id,
                    "journalEntryId": je.id,
                    "voucherNo":      je.voucher_no,
                    "entryDate":      _fmt_date(je.entry_date),
                    "slNo":           idx,
                    "ccCode":         cc_code,
                    "ccName":         cc.cc_name if cc else "",
                    "description":    desc_map.get(cc_code, ""),
                    "bookedAmount":   booked,
                    "paidAmount":     paid,
                    "balanceAmount":  balance,
                    "currentAmount":  0,
                })

            cr_lines = [l for l in je.lines if l.dr_cr == "Cr"]
            entries_meta.append({
                "id":          je.id,
                "voucherNo":   je.voucher_no,
                "entryDate":   _fmt_date(je.entry_date),
                "vendorId":    cr_lines[0].vendor_id    if cr_lines else None,
                "vendorName":  cr_lines[0].vendor.ledger_name if (cr_lines and cr_lines[0].vendor) else None,
            })

        return res("Multi-voucher payment items fetched", {
            "entries": entries_meta,
            "items":   all_items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def _create_voucher_payment(data, user_id, project_code):
    """Create a voucher-type bill payment receipt."""
    payment_mode = data.get("paymentMode")
    if payment_mode == "Bank" and not data.get("bankAcId"):
        return res("Bank account is required for Bank payment mode", [], 400)
    if payment_mode == "Cash" and not data.get("cashAcId"):
        return res("Cash account is required for Cash payment mode", [], 400)

    je_ids = data.get("journalEntryIds") or []
    if not je_ids and data.get("journalEntryId"):
        je_ids = [data["journalEntryId"]]
    je_ids = [int(j) for j in je_ids]
    if not je_ids:
        return res("journalEntryId(s) required for voucher payment", [], 400)

    entries = {je.id: je for je in JournalEntryMaster.query.filter(
        JournalEntryMaster.id.in_(je_ids)
    ).all()}
    for jid in je_ids:
        je = entries.get(jid)
        if not je:
            return res(f"Journal entry {jid} not found", [], 404)
        if je.workflow_status != "Approved":
            return res(f"Journal entry {je.voucher_no} is not Approved", [], 400)
        if je.entry_mode not in ("new_voucher", "bulk_docket"):
            return res(f"Journal entry {je.voucher_no} is not a voucher type", [], 400)

        # Guard: reject if this JE already has an active (non-terminal) payment receipt
        active_primary = BillPaymentReceiptMaster.query.filter(
            BillPaymentReceiptMaster.journal_entry_id == je.id,
            BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
        ).first()
        if not active_primary:
            dr_line_ids = [l.id for l in je.lines if l.dr_cr == "Dr" and l.account_type == "CC"]
            if dr_line_ids:
                active_primary = (
                    BillPaymentReceiptMaster.query
                    .filter(
                        BillPaymentReceiptMaster.id.in_(
                            db.session.query(BillPaymentReceiptItem.receipt_id)
                            .filter(BillPaymentReceiptItem.je_line_id.in_(dr_line_ids))
                        ),
                        BillPaymentReceiptMaster.workflow_status.notin_(["Approved", "Rejected"]),
                    )
                    .first()
                )
        if active_primary:
            return res(
                f"Journal entry {je.voucher_no} already has an active payment in {active_primary.workflow_status} status",
                [], 400
            )

    primary_je = entries[je_ids[0]]

    items = data.get("items", [])
    if not items:
        return res("At least one item required", [], 400)

    basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
    discount    = Decimal(str(data.get("discount")  or 0))
    round_off   = Decimal(str(data.get("roundOff")  or 0))
    total       = basic_total - discount + round_off

    try:
        r = BillPaymentReceiptMaster(
            receipt_no       = _generate_receipt_no(),
            receipt_uuid     = str(_uuid.uuid4()),
            payment_type     = "voucher",
            payment_date     = _parse_date(data.get("paymentDate")) or date.today(),
            purchase_bill_id = None,
            journal_entry_id = je_ids[0],
            project_code     = project_code,
            vendor_id        = data.get("vendorId") or None,
            payment_mode     = payment_mode,
            cash_ac_id       = data.get("cashAcId") or None,
            bank_ac_id       = data.get("bankAcId") or None,
            utr_voucher_no   = data.get("utrVoucherNo"),
            payment_remarks  = data.get("paymentRemarks"),
            basic_amount         = basic_total,
            gst_amount           = Decimal("0"),
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(r)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(BillPaymentReceiptItem(
                receipt_id     = r.id,
                pb_item_id     = None,
                je_line_id     = row.get("jeLineId") or None,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                current_amount = Decimal(str(row.get("currentAmount") or 0)),
            ))

        db.session.commit()
        return res("Voucher payment receipt created", {
            "id":          r.id,
            "receiptNo":   r.receipt_no,
            "receiptUuid": r.receipt_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def create_bill_payment_receipt(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        payment_type = data.get("paymentType") or "bill"

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create bill payment receipts", [], 403)

        if payment_type == "voucher":
            return _create_voucher_payment(data, user_id, project_code)

        # ── BILL PAYMENT ─────────────────────────────────────────────
        # Support multi-bill: purchaseBillIds (array) or single purchaseBillId
        purchase_bill_ids = data.get("purchaseBillIds") or []
        if not purchase_bill_ids and data.get("purchaseBillId"):
            purchase_bill_ids = [data["purchaseBillId"]]
        purchase_bill_ids = [int(b) for b in purchase_bill_ids]
        if not purchase_bill_ids:
            return res("purchaseBillId(s) required", [], 400)

        # Load and validate all bills
        bills_map = {b.id: b for b in PurchaseBillMaster.query.filter(
            PurchaseBillMaster.id.in_(purchase_bill_ids)
        ).all()}
        for bid in purchase_bill_ids:
            b = bills_map.get(bid)
            if not b:
                return res(f"Purchase bill {bid} not found", [], 404)
            if b.workflow_status != "Approved":
                return res(f"Purchase bill {b.purchase_bill_no} is not Approved", [], 400)

        # Primary bill (first in list) used for the FK and header fields
        primary_bill_id = purchase_bill_ids[0]
        bill = bills_map[primary_bill_id]
        is_multi = len(purchase_bill_ids) > 1

        payment_mode = data.get("paymentMode")
        if payment_mode == "Bank" and not data.get("bankAcId"):
            return res("Bank account is required for Bank payment mode", [], 400)
        if payment_mode == "Cash" and not data.get("cashAcId"):
            return res("Cash account is required for Cash payment mode", [], 400)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        gst_total = sum(
            Decimal(str(g.get("currentAmount") or 0))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))
        total     = basic_total + gst_total - discount + round_off

        order_no = (
            (bill.brr.order.order_no    if bill.brr and bill.brr.order    else None) or
            (bill.brr.pw_order.order_no if bill.brr and bill.brr.pw_order else None)
        )

        r = BillPaymentReceiptMaster(
            receipt_no       = _generate_receipt_no(),
            receipt_uuid     = str(_uuid.uuid4()),
            payment_type     = "bill",
            payment_date     = _parse_date(data.get("paymentDate")) or date.today(),
            purchase_bill_id = primary_bill_id,
            bvs_date         = bill.processing_date,
            vendor_bill_no   = bill.vendor_bill_no,
            vendor_bill_date = bill.vendor_bill_date,
            order_no         = order_no,
            project_code     = project_code,
            vendor_id        = data.get("vendorId") or bill.vendor_id,
            payment_mode     = data.get("paymentMode"),
            cash_ac_id       = data.get("cashAcId")  or None,
            bank_ac_id       = data.get("bankAcId")  or None,
            utr_voucher_no   = data.get("utrVoucherNo"),
            payment_remarks  = data.get("paymentRemarks"),
            basic_amount         = basic_total,
            gst_amount           = gst_total,
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(r)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(BillPaymentReceiptItem(
                receipt_id     = r.id,
                pb_item_id     = row.get("pbItemId") or None,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                current_amount = Decimal(str(row.get("currentAmount") or 0)),
            ))

        for g in gst_lines:
            raw_gst_type = g.get("gstType") or ""
            # For multi-bill: frontend sends "{bill_id}:IGST"; store as-is.
            # For single-bill: store plain "IGST" (no prefix) for backward compat.
            gst_type_stored = raw_gst_type if (is_multi or ":" in raw_gst_type) else raw_gst_type
            db.session.add(BillPaymentReceiptGst(
                receipt_id     = r.id,
                gst_type       = gst_type_stored,
                cc_code        = g.get("ccCode"),
                cc_name        = g.get("ccName"),
                booked_amount  = Decimal(str(g.get("bookedAmount")  or 0)),
                current_amount = Decimal(str(g.get("currentAmount") or 0)),
                is_selected    = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Bill payment receipt created", {
            "id":          r.id,
            "receiptNo":   r.receipt_no,
            "receiptUuid": r.receipt_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BillPaymentReceiptMaster.query.filter(
            BillPaymentReceiptMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(BillPaymentReceiptMaster.workflow_status == data.get("workflowStatus"))
        if data.get("vendorId"):
            query = query.filter(BillPaymentReceiptMaster.vendor_id == int(data.get("vendorId")))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    BillPaymentReceiptMaster.receipt_no.ilike(term),
                    BillPaymentReceiptMaster.utr_voucher_no.ilike(term),
                    BillPaymentReceiptMaster.vendor_bill_no.ilike(term),
                )
            )

        rows = query.order_by(BillPaymentReceiptMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "receiptNo":          r.receipt_no,
                "paymentDate":        _fmt_date(r.payment_date),
                "purchaseBillId":     r.purchase_bill_id,
                "purchaseBillNo":     r.purchase_bill.purchase_bill_no if r.purchase_bill else None,
                "bvsDate":            _fmt_date(r.bvs_date),
                "vendorBillNo":       r.vendor_bill_no,
                "orderNo":            r.order_no,
                "vendorId":           r.vendor_id,
                "vendorName":         r.vendor.ledger_name if r.vendor else None,
                "paymentMode":        r.payment_mode,
                "utrVoucherNo":       r.utr_voucher_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Bill payment list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_details(receipt_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        return res("Bill payment details fetched", _build_detail_payload(r), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_by_uuid(receipt_uuid):
    try:
        r = BillPaymentReceiptMaster.query.filter_by(receipt_uuid=receipt_uuid).first()
        if not r:
            return res("Bill payment receipt not found", [], 404)
        return res("Bill payment details fetched", _build_detail_payload(r), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_bill_payment_receipt(receipt_id, data, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if r.locked:
            return res("Bill payment receipt is locked and cannot be edited", [], 400)
        if r.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(r.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit bill payment receipts", [], 403)

        payment_mode = data.get("paymentMode") or r.payment_mode
        if payment_mode == "Bank" and not (data.get("bankAcId") or r.bank_ac_id):
            return res("Bank account is required for Bank payment mode", [], 400)
        if payment_mode == "Cash" and not (data.get("cashAcId") or r.cash_ac_id):
            return res("Cash account is required for Cash payment mode", [], 400)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        for key, attr in [
            ("paymentDate",    "payment_date"),
            ("paymentMode",    "payment_mode"),
            ("cashAcId",       "cash_ac_id"),
            ("bankAcId",       "bank_ac_id"),
            ("utrVoucherNo",   "utr_voucher_no"),
            ("paymentRemarks", "payment_remarks"),
        ]:
            if data.get(key) is not None:
                val = _parse_date(data[key]) if attr == "payment_date" else (data[key] or None)
                setattr(r, attr, val)

        BillPaymentReceiptItem.query.filter_by(receipt_id=r.id).delete()
        BillPaymentReceiptGst.query.filter_by(receipt_id=r.id).delete()
        db.session.flush()

        is_voucher = (r.payment_type or "bill") == "voucher"
        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)

        if is_voucher:
            for idx, row in enumerate(items, start=1):
                db.session.add(BillPaymentReceiptItem(
                    receipt_id     = r.id,
                    pb_item_id     = None,
                    je_line_id     = row.get("jeLineId") or None,
                    sl_no          = row.get("slNo") or idx,
                    cc_code        = row.get("ccCode"),
                    cc_name        = row.get("ccName"),
                    booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                    current_amount = Decimal(str(row.get("currentAmount") or 0)),
                ))
            gst_total = Decimal("0")
        else:
            gst_lines = data.get("gstLines", [])
            gst_total = sum(
                Decimal(str(g.get("currentAmount") or 0))
                for g in gst_lines if g.get("isSelected")
            )
            for idx, row in enumerate(items, start=1):
                db.session.add(BillPaymentReceiptItem(
                    receipt_id     = r.id,
                    pb_item_id     = row.get("pbItemId") or None,
                    sl_no          = row.get("slNo") or idx,
                    cc_code        = row.get("ccCode"),
                    cc_name        = row.get("ccName"),
                    booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                    current_amount = Decimal(str(row.get("currentAmount") or 0)),
                ))
            edit_is_multi = any(":" in (g.get("gstType") or "") for g in gst_lines)
            for g in gst_lines:
                raw_gst_type = g.get("gstType") or ""
                gst_type_stored = raw_gst_type if (edit_is_multi or ":" in raw_gst_type) else raw_gst_type
                db.session.add(BillPaymentReceiptGst(
                    receipt_id     = r.id,
                    gst_type       = gst_type_stored,
                    cc_code        = g.get("ccCode"),
                    cc_name        = g.get("ccName"),
                    booked_amount  = Decimal(str(g.get("bookedAmount")  or 0)),
                    current_amount = Decimal(str(g.get("currentAmount") or 0)),
                    is_selected    = bool(g.get("isSelected")),
                ))

        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        r.basic_amount         = basic_total
        r.gst_amount           = gst_total
        r.discount             = discount
        r.round_off            = round_off
        r.total_invoice_amount = basic_total + gst_total - discount + round_off

        if r.workflow_status == "Reback":
            r.correction_sent_at = None

        r.updated_by = user_id
        r.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Bill payment receipt updated", {"id": r.id, "receiptNo": r.receipt_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_bill_payment(receipt_id, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if r.workflow_status not in ("Draft", "Reback"):
            return res("Bill payment receipt already submitted", [], 400)
        if not r.items:
            return res("Bill payment receipt has no items", [], 400)

        if r.workflow_status == "Reback":
            r.current_level = 0

        first_level = get_first_approver(r.project_code, _MODULE)

        if not first_level:
            r.workflow_status   = "Approved"
            r.locked            = True
            r.approved_by       = user_id
            r.submitted_at      = datetime.utcnow()
            r.final_approved_at = datetime.utcnow()
        else:
            r.workflow_status = f"Pending_L{first_level.level_no}"
            r.current_level   = first_level.level_no
            r.locked          = True
            r.submitted_at    = datetime.utcnow()

        create_history(
            project_code = r.project_code,
            module_code  = _MODULE,
            record_id    = r.id,
            level_no     = r.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        r.submitted_by = user_id
        r.updated_by   = user_id
        r.updated_at   = datetime.utcnow()

        db.session.commit()

        try:
            submitter = User.query.get(user_id)
            submitter_name = submitter.username if submitter else str(user_id)
            if first_level:
                wa.on_submit(
                    module_code="bill_payment_receipt",
                    doc_no=r.receipt_no,
                    uuid=str(r.receipt_uuid),
                    project_code=r.project_code,
                    submitter_name=submitter_name,
                    approver_user=first_level.user,
                    current_level=first_level.level_no,
                    record_id=r.id,
                )
        except Exception:
            pass

        return res("Bill payment receipt submitted", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_bill_payment(receipt_id, approved_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending approval", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(r.project_code, _MODULE, r.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(r.project_code, _MODULE, r.current_level)

        if next_level:
            create_history(
                project_code=r.project_code, module_code=_MODULE,
                record_id=r.id, level_no=r.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            r.current_level   = next_level.level_no
            r.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=r.project_code, module_code=_MODULE,
                record_id=r.id, level_no=r.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            r.workflow_status   = "Approved"
            r.locked            = True
            r.approved_by       = approved_by
            r.final_approved_at = datetime.utcnow()

        r.updated_by = approved_by
        r.updated_at = datetime.utcnow()

        if r.workflow_status == "Approved":
            db.session.flush()
            try:
                from app.modules.finance.accounting import post_document
                post_document("bill_payment", r.id, approved_by)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Accounting posting failed for BPR {r.id}: {e}")

        db.session.commit()

        try:
            approver_user = User.query.get(approved_by)
            approver_name = approver_user.username if approver_user else str(approved_by)
            if next_level:
                wa.on_approve(
                    module_code="bill_payment_receipt",
                    doc_no=r.receipt_no,
                    uuid=str(r.receipt_uuid),
                    project_code=r.project_code,
                    approver_name=approver_name,
                    prev_level=r.current_level,
                    next_approver_user=next_level.user,
                    next_level=next_level.level_no,
                    record_id=r.id,
                )
            else:
                creator_user = User.query.get(r.created_by)
                wa.on_final_approve(
                    module_code="bill_payment_receipt",
                    doc_no=r.receipt_no,
                    uuid=str(r.receipt_uuid),
                    project_code=r.project_code,
                    approver_name=approver_name,
                    creator_user=creator_user,
                    record_id=r.id,
                )
        except Exception:
            pass

        return res("Bill payment receipt approved", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_bill_payment(receipt_id, reback_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        r.workflow_status    = "Reback"
        r.locked             = False
        r.correction_sent_at = datetime.utcnow()
        r.updated_by         = reback_by
        r.updated_at         = datetime.utcnow()

        create_history(
            project_code=r.project_code, module_code=_MODULE,
            record_id=r.id, level_no=r.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        try:
            reback_user = User.query.get(reback_by)
            reback_name = reback_user.username if reback_user else str(reback_by)
            creator_user = User.query.get(r.created_by)
            wa.on_reback(
                module_code="bill_payment_receipt",
                doc_no=r.receipt_no,
                uuid=str(r.receipt_uuid),
                project_code=r.project_code,
                approver_name=reback_name,
                creator_user=creator_user,
                comments=comments,
                record_id=r.id,
            )
        except Exception:
            pass

        return res("Bill payment receipt sent for correction", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_bill_payment(receipt_id, rejected_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        r.workflow_status = "Rejected"
        r.locked          = True
        r.rejected_at     = datetime.utcnow()
        r.rejected_by     = rejected_by
        r.status          = "Inactive"
        r.updated_by      = rejected_by
        r.updated_at      = datetime.utcnow()

        create_history(
            project_code=r.project_code, module_code=_MODULE,
            record_id=r.id, level_no=r.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        try:
            rejected_user = User.query.get(rejected_by)
            rejected_name = rejected_user.username if rejected_user else str(rejected_by)
            creator_user = User.query.get(r.created_by)
            wa.on_reject(
                module_code="bill_payment_receipt",
                doc_no=r.receipt_no,
                uuid=str(r.receipt_uuid),
                project_code=r.project_code,
                approver_name=rejected_name,
                creator_user=creator_user,
                comments=comments,
                record_id=r.id,
            )
        except Exception:
            pass

        return res("Bill payment receipt rejected", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_history(receipt_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)

        rows = get_history(_MODULE, r.id)

        history = [
            {
                "id":        h.id,
                "action":    h.action,
                "level":     h.level_no,
                "comments":  h.comments,
                "actionBy":  h.user.username if h.user else None,
                "createdAt": h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else None,
            }
            for h in rows
        ]

        steps = get_approval_steps(r.project_code, _MODULE, r, rows)

        return res("History fetched", {
            "workflowStatus": r.workflow_status,
            "currentLevel":   r.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_my_approval_status(receipt_id, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        data = get_my_approval_status(r.project_code, _MODULE, r, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


def delete_bill_payment(receipt_id):
    try:
        receipt = BillPaymentReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Bill Payment not found", [], 404)
        if receipt.locked:
            return res("Only draft Bill Payment can be deleted", [], 400)
        from app.modules.finance.accounting.deletion_guard import check_posted_before_delete
        can_delete, msg = check_posted_before_delete("BillPaymentReceiptMaster", receipt_id)
        if not can_delete:
            return res(msg, [], 400)
        BillPaymentReceiptGst.query.filter_by(receipt_id=receipt.id).delete()
        BillPaymentReceiptItem.query.filter_by(receipt_id=receipt.id).delete()
        db.session.delete(receipt)
        db.session.commit()
        from app.modules.delete_manager.service import auto_complete_check
        auto_complete_check("BILL_PAYMENT", receipt_id)
        return res("Bill Payment deleted successfully", [], 200)
    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
