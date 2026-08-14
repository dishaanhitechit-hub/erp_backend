from datetime import datetime, date as date_type
from app.extensions import db
from app.models.purchaseVoucher import PurchaseVoucherMaster
from app.models.purchaseBill import PurchaseBillMaster
from app.models.paymentVoucher import PaymentVoucherMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.saleBill import SaleBillMaster
from app.models.saleReceiptBilling import SaleReceiptBillingMaster
from app.models.debitNote import DebitNoteMaster
from app.models.creditNote import CreditNoteMaster
from app.models.project import Project
from app.models.vendor import Vendor
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


def _vendor_map(ids):
    """Batch load vendor ledger_name by id set."""
    if not ids:
        return {}
    rows = Vendor.query.filter(Vendor.id.in_(ids)).all()
    return {v.id: v.ledger_name for v in rows}


def _build_project_entries(project_code, from_date=None, to_date=None):
    entries = []

    def _df(q, date_col):
        if from_date:
            q = q.filter(date_col >= from_date)
        if to_date:
            q = q.filter(date_col <= to_date)
        return q

    # ── Fetch all records up front
    sale_bills = _df(
        SaleBillMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        SaleBillMaster.invoice_date
    ).all()

    sale_receipts = _df(
        SaleReceiptBillingMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        SaleReceiptBillingMaster.invoice_date
    ).all()

    pv_records = _df(
        PurchaseVoucherMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        PurchaseVoucherMaster.processing_date
    ).all()

    pb_records = _df(
        PurchaseBillMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        PurchaseBillMaster.processing_date
    ).all()

    pvm_records = _df(
        PaymentVoucherMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        PaymentVoucherMaster.payment_date
    ).all()

    bpr_records = _df(
        BillPaymentReceiptMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        BillPaymentReceiptMaster.payment_date
    ).all()

    dn_records = _df(
        DebitNoteMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        DebitNoteMaster.entry_date
    ).all()

    cn_records = _df(
        CreditNoteMaster.query.filter_by(project_code=project_code, workflow_status="Approved"),
        CreditNoteMaster.entry_date
    ).all()

    # Batch load vendor names
    vendor_ids = set()
    for r in pv_records + pb_records + pvm_records + bpr_records:
        if r.vendor_id:
            vendor_ids.add(r.vendor_id)
    for r in dn_records + cn_records:
        if r.vendor_id:
            vendor_ids.add(r.vendor_id)
    v_map = _vendor_map(vendor_ids)

    # ── 1. Sale Bill → Debit (we billed client, receivable)
    for r in sale_bills:
        entries.append({
            "date":        _fmt(r.invoice_date),
            "_sort_dt":    r.invoice_date,
            "_sort_id":    r.id,
            "docType":     "Sale Bill",
            "docNo":       r.sale_bill_no,
            "docId":       r.id,
            "vendorName":  None,
            "particular":  "Sale Invoice " + r.sale_bill_no,
            "debit":       float(r.total_invoice_amount or 0),
            "credit":      0.0,
        })

    # ── 2. Sale Receipt → Debit (client paid us, cash in)
    for r in sale_receipts:
        entries.append({
            "date":        _fmt(r.invoice_date),
            "_sort_dt":    r.invoice_date,
            "_sort_id":    r.id,
            "docType":     "Sale Receipt",
            "docNo":       r.srb_no,
            "docId":       r.id,
            "vendorName":  None,
            "particular":  "Sale Receipt " + r.srb_no,
            "debit":       float(r.total_invoice_amount or 0),
            "credit":      0.0,
        })

    # ── 3. Purchase Voucher → Credit (vendor billed us, payable)
    for r in pv_records:
        entries.append({
            "date":        _fmt(r.processing_date),
            "_sort_dt":    r.processing_date,
            "_sort_id":    r.id,
            "docType":     "Purchase Voucher",
            "docNo":       r.voucher_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id),
            "particular":  "Purchase Voucher " + r.voucher_no,
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 4. Purchase Bill → Credit (vendor billed us, payable)
    for r in pb_records:
        entries.append({
            "date":        _fmt(r.processing_date),
            "_sort_dt":    r.processing_date,
            "_sort_id":    r.id,
            "docType":     "Purchase Bill",
            "docNo":       r.purchase_bill_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id),
            "particular":  "Purchase Bill " + r.purchase_bill_no + (f" | {r.vendor_bill_no}" if r.vendor_bill_no else ""),
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 5. Payment Voucher → Credit (we paid vendor, cash out)
    for r in pvm_records:
        entries.append({
            "date":        _fmt(r.payment_date),
            "_sort_dt":    r.payment_date,
            "_sort_id":    r.id,
            "docType":     "Payment Voucher",
            "docNo":       r.payment_vouch_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id),
            "particular":  "Payment Voucher " + r.payment_vouch_no + (f" | UTR: {r.utr_voucher_no}" if r.utr_voucher_no else ""),
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 6. Bill Payment Receipt → Credit (we paid vendor, cash out)
    for r in bpr_records:
        entries.append({
            "date":        _fmt(r.payment_date),
            "_sort_dt":    r.payment_date,
            "_sort_id":    r.id,
            "docType":     "Bill Payment",
            "docNo":       r.receipt_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id),
            "particular":  "Bill Payment " + r.receipt_no + (f" | UTR: {r.utr_voucher_no}" if r.utr_voucher_no else ""),
            "debit":       0.0,
            "credit":      float(r.total_invoice_amount or 0),
        })

    # ── 7. Debit Note → Debit (reduces payable, net positive for us)
    for r in dn_records:
        entries.append({
            "date":        _fmt(r.entry_date),
            "_sort_dt":    r.entry_date,
            "_sort_id":    r.id,
            "docType":     "Debit Note",
            "docNo":       r.debit_note_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id) if r.vendor_id else r.vendor_name,
            "particular":  "Debit Note " + r.debit_note_no,
            "debit":       float(r.total_amount or 0),
            "credit":      0.0,
        })

    # ── 8. Credit Note → Credit (increases payable)
    for r in cn_records:
        entries.append({
            "date":        _fmt(r.entry_date),
            "_sort_dt":    r.entry_date,
            "_sort_id":    r.id,
            "docType":     "Credit Note",
            "docNo":       r.credit_note_no,
            "docId":       r.id,
            "vendorName":  v_map.get(r.vendor_id) if r.vendor_id else r.vendor_name,
            "particular":  "Credit Note " + r.credit_note_no,
            "debit":       0.0,
            "credit":      float(r.total_amount or 0),
        })

    # Sort chronologically
    entries.sort(key=lambda e: (e["_sort_dt"] or date_type.min, e["_sort_id"]))

    # Running balance: Debit = income/receivable (+), Credit = expense/payable (−)
    balance = 0.0
    for e in entries:
        balance += e["debit"] - e["credit"]
        e["balance"]     = round(abs(balance), 2)
        e["balanceType"] = "Dr" if balance >= 0 else "Cr"
        del e["_sort_dt"]
        del e["_sort_id"]

    total_debit  = round(sum(e["debit"]  for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing      = round(total_debit - total_credit, 2)

    summary = {
        "totalDebit":     total_debit,
        "totalCredit":    total_credit,
        "closingBalance": round(abs(closing), 2),
        "balanceType":    "Dr" if closing >= 0 else "Cr",
    }
    return summary, entries


# ══════════════════════════════════════════════════════════════════
# PUBLIC FUNCTION
# ══════════════════════════════════════════════════════════════════

def get_my_ledger(data):
    project_code = data.get("projectCode") or None
    from_date    = _parse_date(data.get("fromDate"))
    to_date      = _parse_date(data.get("toDate"))

    if project_code:
        proj = Project.query.filter_by(project_code=project_code).first()
        summary, entries = _build_project_entries(project_code, from_date, to_date)
        return res("My ledger fetched", {
            "mode":        "project",
            "projectCode": project_code,
            "projectName": proj.project_name if proj else None,
            "clientName":  proj.client_name  if proj else None,
            "filters":     {
                "fromDate": str(from_date) if from_date else None,
                "toDate":   str(to_date)   if to_date   else None,
            },
            "summary": summary,
            "entries": entries,
        }, 200)

    # All-projects mode
    projects    = Project.query.order_by(Project.project_code).all()
    all_debit   = 0.0
    all_credit  = 0.0
    proj_blocks = []

    for proj in projects:
        summary, entries = _build_project_entries(proj.project_code, from_date, to_date)
        if not entries:
            continue
        all_debit  += summary["totalDebit"]
        all_credit += summary["totalCredit"]
        proj_blocks.append({
            "projectCode": proj.project_code,
            "projectName": proj.project_name,
            "clientName":  proj.client_name,
            "summary":     summary,
            "entries":     entries,
        })

    closing = round(all_debit - all_credit, 2)
    return res("My ledger fetched", {
        "mode":    "all",
        "filters": {
            "fromDate": str(from_date) if from_date else None,
            "toDate":   str(to_date)   if to_date   else None,
        },
        "summary": {
            "totalDebit":     round(all_debit, 2),
            "totalCredit":    round(all_credit, 2),
            "closingBalance": round(abs(closing), 2),
            "balanceType":    "Dr" if closing >= 0 else "Cr",
        },
        "projects": proj_blocks,
    }, 200)
