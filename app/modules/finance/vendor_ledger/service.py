from datetime import datetime, date as date_type
from app.extensions import db
from app.models.vendor import Vendor
from app.models.purchaseVoucher import PurchaseVoucherMaster
from app.models.purchaseBill import PurchaseBillMaster
from app.models.paymentVoucher import PaymentVoucherMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.debitNote import DebitNoteMaster
from app.models.creditNote import CreditNoteMaster
from app.response import res


def _fmt(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _build_ledger(vendor_id, project_code=None, from_date=None, to_date=None):
    entries = []

    def _apply_filters(q, model, date_col):
        if project_code:
            q = q.filter(model.project_code == project_code)
        if from_date:
            q = q.filter(date_col >= from_date)
        if to_date:
            q = q.filter(date_col <= to_date)
        return q

    # ── 1. Purchase Voucher → Credit (we owe vendor)
    for r in _apply_filters(
        PurchaseVoucherMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        PurchaseVoucherMaster, PurchaseVoucherMaster.processing_date
    ).all():
        entries.append({
            "date":        _fmt(r.processing_date),
            "_sort_dt":    r.processing_date,
            "_sort_id":    r.id,
            "docType":     "Purchase Voucher",
            "docNo":       r.voucher_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Purchase Voucher " + r.voucher_no + (f" | {r.vendor_voucher_no}" if r.vendor_voucher_no else ""),
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 2. Purchase Bill → Credit (we owe vendor)
    for r in _apply_filters(
        PurchaseBillMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        PurchaseBillMaster, PurchaseBillMaster.processing_date
    ).all():
        entries.append({
            "date":        _fmt(r.processing_date),
            "_sort_dt":    r.processing_date,
            "_sort_id":    r.id,
            "docType":     "Purchase Bill",
            "docNo":       r.purchase_bill_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Purchase Bill " + r.purchase_bill_no + (f" | {r.vendor_bill_no}" if r.vendor_bill_no else ""),
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 3. Payment Voucher → Debit (we paid vendor)
    for r in _apply_filters(
        PaymentVoucherMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        PaymentVoucherMaster, PaymentVoucherMaster.payment_date
    ).all():
        entries.append({
            "date":        _fmt(r.payment_date),
            "_sort_dt":    r.payment_date,
            "_sort_id":    r.id,
            "docType":     "Payment Voucher",
            "docNo":       r.payment_vouch_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Payment Voucher " + r.payment_vouch_no + (f" | UTR: {r.utr_voucher_no}" if r.utr_voucher_no else ""),
            "debit":       float(r.total_invoice_amount or 0),
            "credit":      0.0,
        })

    # ── 4. Bill Payment Receipt → Debit (we paid vendor)
    for r in _apply_filters(
        BillPaymentReceiptMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        BillPaymentReceiptMaster, BillPaymentReceiptMaster.payment_date
    ).all():
        entries.append({
            "date":        _fmt(r.payment_date),
            "_sort_dt":    r.payment_date,
            "_sort_id":    r.id,
            "docType":     "Bill Payment",
            "docNo":       r.receipt_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Bill Payment " + r.receipt_no + (f" | UTR: {r.utr_voucher_no}" if r.utr_voucher_no else ""),
            "debit":       float(r.total_invoice_amount or 0),
            "credit":      0.0,
        })

    # ── 5. Debit Note → Debit (reduces our payable)
    for r in _apply_filters(
        DebitNoteMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        DebitNoteMaster, DebitNoteMaster.entry_date
    ).all():
        entries.append({
            "date":        _fmt(r.entry_date),
            "_sort_dt":    r.entry_date,
            "_sort_id":    r.id,
            "docType":     "Debit Note",
            "docNo":       r.debit_note_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Debit Note " + r.debit_note_no + (f" | Bill: {r.bill_number}" if r.bill_number else ""),
            "debit":       float(r.total_amount or 0),
            "credit":      0.0,
        })

    # ── 6. Credit Note → Credit (increases our payable)
    for r in _apply_filters(
        CreditNoteMaster.query.filter_by(vendor_id=vendor_id, workflow_status="Approved"),
        CreditNoteMaster, CreditNoteMaster.entry_date
    ).all():
        entries.append({
            "date":        _fmt(r.entry_date),
            "_sort_dt":    r.entry_date,
            "_sort_id":    r.id,
            "docType":     "Credit Note",
            "docNo":       r.credit_note_no,
            "docId":       r.id,
            "projectCode": r.project_code,
            "particular":  "Credit Note " + r.credit_note_no + (f" | Bill: {r.bill_number}" if r.bill_number else ""),
            "debit":       0.0,
            "credit":      float(r.total_amount or 0),
        })

    # Sort chronologically
    entries.sort(key=lambda e: (e["_sort_dt"] or date_type.min, e["_sort_id"]))

    # Running balance: Credit = we owe vendor (+), Debit = we paid (−)
    balance = 0.0
    for e in entries:
        balance += e["credit"] - e["debit"]
        e["balance"]     = round(abs(balance), 2)
        e["balanceType"] = "Cr" if balance >= 0 else "Dr"
        del e["_sort_dt"]
        del e["_sort_id"]

    total_debit  = round(sum(e["debit"]  for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing      = round(total_credit - total_debit, 2)

    summary = {
        "totalDebit":     total_debit,
        "totalCredit":    total_credit,
        "closingBalance": round(abs(closing), 2),
        "balanceType":    "Cr" if closing >= 0 else "Dr",
    }
    return summary, entries


# ══════════════════════════════════════════════════════════════════
# PUBLIC FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def get_vendor_ledger(data):
    vendor_id    = data.get("vendorId")
    project_code = data.get("projectCode") or None
    from_date    = _parse_date(data.get("fromDate"))
    to_date      = _parse_date(data.get("toDate"))

    if not vendor_id:
        return res("vendorId required", [], 400)

    vendor = Vendor.query.get(int(vendor_id))
    if not vendor:
        return res("Vendor not found", [], 404)

    summary, entries = _build_ledger(vendor.id, project_code, from_date, to_date)

    return res("Vendor ledger fetched", {
        "vendor":  {
            "id":         vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "gstin":      vendor.gstin,
        },
        "filters": {"projectCode": project_code, "fromDate": str(from_date) if from_date else None, "toDate": str(to_date) if to_date else None},
        "summary": summary,
        "entries": entries,
    }, 200)


def get_vendor_ledger_by_uuid(vendor_uuid, data):
    vendor = Vendor.query.filter_by(vendor_uuid=vendor_uuid).first()
    if not vendor:
        return res("Vendor not found", [], 404)

    project_code = data.get("projectCode") or None
    from_date    = _parse_date(data.get("fromDate"))
    to_date      = _parse_date(data.get("toDate"))

    summary, entries = _build_ledger(vendor.id, project_code, from_date, to_date)

    return res("Vendor ledger fetched", {
        "vendor":  {
            "id":         vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "gstin":      vendor.gstin,
        },
        "filters": {"projectCode": project_code, "fromDate": str(from_date) if from_date else None, "toDate": str(to_date) if to_date else None},
        "summary": summary,
        "entries": entries,
    }, 200)
