"""
Module-specific posting rules.

Each function receives a source_id (PK of the master table) and returns:
  (header_data, lines_data)

header_data = {
    "posting_date": date,
    "voucher_no": str,
    "project_code": str | None,
    "remarks": str | None,
}

lines_data = [
    {
        "account_type": "CC" | "Vendor" | "BankCash",
        "cc_id": int | None,
        "vendor_id": int | None,
        "bank_cash_id": int | None,
        "dr_cr": "Dr" | "Cr",
        "amount": Decimal,
        "project_code": str | None,
        "cost_centre_code": str | None,
        "gst_type": str | None,
        "gst_rate": Decimal | None,
        "source_line_id": int | None,
        "narration": str | None,
    },
    ...
]
"""

from decimal import Decimal

from app.models.cc_code import CCCode


def _resolve_cc_id(cc_code_str):
    """Resolve a CC-code string to cc_codes.id. Returns (cc_id, cc_code_str)."""
    if not cc_code_str:
        return None, None
    cc = CCCode.query.filter(CCCode.cc_code == cc_code_str.upper().strip()).first()
    return (cc.id if cc else None), cc_code_str.upper().strip()


def _d(val):
    """Safe Decimal conversion."""
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _cc_line(cc_code_str, dr_cr, amount, project_code=None, gst_type=None, gst_rate=None, source_line_id=None, narration=None):
    cc_id, cc_code = _resolve_cc_id(cc_code_str)
    return {
        "account_type": "CC",
        "cc_id": cc_id,
        "dr_cr": dr_cr,
        "amount": amount,
        "project_code": project_code,
        "cost_centre_code": cc_code,
        "gst_type": gst_type,
        "gst_rate": gst_rate,
        "source_line_id": source_line_id,
        "narration": narration,
    }


def _vendor_line(vendor_id, dr_cr, amount, project_code=None, source_line_id=None, narration=None):
    return {
        "account_type": "Vendor",
        "vendor_id": vendor_id,
        "dr_cr": dr_cr,
        "amount": amount,
        "project_code": project_code,
        "source_line_id": source_line_id,
        "narration": narration,
    }


def _bank_line(bank_cash_id, dr_cr, amount, project_code=None, source_line_id=None, narration=None):
    return {
        "account_type": "BankCash",
        "bank_cash_id": bank_cash_id,
        "dr_cr": dr_cr,
        "amount": amount,
        "project_code": project_code,
        "source_line_id": source_line_id,
        "narration": narration,
    }


# ---------------------------------------------------------------------------
# 1. Purchase Bill
# ---------------------------------------------------------------------------

def _post_purchase_bill(source_id):
    from app.models.purchaseBill import PurchaseBillMaster

    bill = PurchaseBillMaster.query.get(source_id)
    if not bill:
        from .posting_engine import PostingError
        raise PostingError(f"PurchaseBill {source_id} not found")

    lines = []

    for item in bill.items:
        amt = _d(item.basic_amount)
        if amt > 0:
            lines.append(_cc_line(
                item.cc_code, "Dr", amt,
                project_code=bill.project_code,
                source_line_id=item.id,
                narration=f"PB expense: {item.cc_code}",
            ))

    for gst in bill.gst_lines:
        if gst.is_selected and _d(gst.gst_amount) > 0:
            lines.append(_cc_line(
                gst.cc_code, "Dr", _d(gst.gst_amount),
                project_code=bill.project_code,
                gst_type=gst.gst_type,
                gst_rate=_d(gst.percent),
                source_line_id=gst.id,
                narration=f"GST Input {gst.gst_type}",
            ))

    total = _d(bill.total_invoice_amount)
    if total > 0 and bill.vendor_id:
        lines.append(_vendor_line(
            bill.vendor_id, "Cr", total,
            project_code=bill.project_code,
            narration=f"Vendor payable: PB {bill.purchase_bill_no}",
        ))

    header = {
        "posting_date": bill.processing_date,
        "voucher_no": bill.purchase_bill_no,
        "project_code": bill.project_code,
        "remarks": bill.remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 2. Payment Voucher
# ---------------------------------------------------------------------------

def _post_payment_voucher(source_id):
    from app.models.paymentVoucher import PaymentVoucherMaster

    pv = PaymentVoucherMaster.query.get(source_id)
    if not pv:
        from .posting_engine import PostingError
        raise PostingError(f"PaymentVoucher {source_id} not found")

    lines = []

    for item in pv.items:
        amt = _d(item.current_amount)
        if amt > 0:
            lines.append(_cc_line(
                item.cc_code, "Dr", amt,
                project_code=pv.project_code,
                source_line_id=item.id,
                narration=f"PV expense: {item.cc_code}",
            ))

    for gst in pv.gst_lines:
        if gst.is_selected and _d(gst.current_amount) > 0:
            lines.append(_cc_line(
                gst.cc_code, "Dr", _d(gst.current_amount),
                project_code=pv.project_code,
                gst_type=gst.gst_type,
                source_line_id=gst.id,
                narration=f"GST Input {gst.gst_type}",
            ))

    bank_cash_id = pv.bank_ac_id if pv.payment_mode == "Bank" else pv.cash_ac_id
    total = _d(pv.total_invoice_amount)
    if total > 0 and bank_cash_id:
        lines.append(_bank_line(
            bank_cash_id, "Cr", total,
            project_code=pv.project_code,
            narration=f"PV payment: {pv.payment_vouch_no}",
        ))

    header = {
        "posting_date": pv.payment_date,
        "voucher_no": pv.payment_vouch_no,
        "project_code": pv.project_code,
        "remarks": pv.payment_remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 3. Bill Payment Receipt (bill mode) — settles PB vendor liability
# ---------------------------------------------------------------------------

def _post_bill_payment_bill(source_id):
    from app.models.billPaymentReceipt import BillPaymentReceiptMaster

    bpr = BillPaymentReceiptMaster.query.get(source_id)
    if not bpr:
        from .posting_engine import PostingError
        raise PostingError(f"BillPaymentReceipt {source_id} not found")

    lines = []
    total = _d(bpr.total_invoice_amount)

    if total > 0 and bpr.vendor_id:
        lines.append(_vendor_line(
            bpr.vendor_id, "Dr", total,
            project_code=bpr.project_code,
            narration=f"BPR bill payment: {bpr.receipt_no}",
        ))

    bank_cash_id = bpr.bank_ac_id if bpr.payment_mode == "Bank" else bpr.cash_ac_id
    if total > 0 and bank_cash_id:
        lines.append(_bank_line(
            bank_cash_id, "Cr", total,
            project_code=bpr.project_code,
            narration=f"BPR payment: {bpr.receipt_no}",
        ))

    header = {
        "posting_date": bpr.payment_date,
        "voucher_no": bpr.receipt_no,
        "project_code": bpr.project_code,
        "remarks": bpr.payment_remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 4. Bill Payment Receipt (voucher mode) — settles JE vendor liability
# ---------------------------------------------------------------------------

def _post_bill_payment_voucher(source_id):
    # Same posting structure as bill mode: Dr Vendor, Cr Bank
    return _post_bill_payment_bill(source_id)


# ---------------------------------------------------------------------------
# 5. Bill Payment Receipt — dispatcher
# ---------------------------------------------------------------------------

def _post_bill_payment_receipt(source_id):
    from app.models.billPaymentReceipt import BillPaymentReceiptMaster
    bpr = BillPaymentReceiptMaster.query.get(source_id)
    if not bpr:
        from .posting_engine import PostingError
        raise PostingError(f"BillPaymentReceipt {source_id} not found")

    if bpr.payment_type == "voucher":
        return _post_bill_payment_voucher(source_id)
    return _post_bill_payment_bill(source_id)


# ---------------------------------------------------------------------------
# 6. Sale Bill
# ---------------------------------------------------------------------------

def _post_sale_bill(source_id):
    from app.models.saleBill import SaleBillMaster
    from app.models.ogSaleOrder import OgSaleOrderMaster

    sb = SaleBillMaster.query.get(source_id)
    if not sb:
        from .posting_engine import PostingError
        raise PostingError(f"SaleBill {source_id} not found")

    lines = []

    # Resolve customer (debtor) via sale_order → OgSaleOrder.debtor_id
    debtor_vendor_id = None
    if sb.sale_order_id:
        so = OgSaleOrderMaster.query.get(sb.sale_order_id)
        if so:
            debtor_vendor_id = so.debtor_id

    total = _d(sb.total_invoice_amount)

    # Dr Customer receivable
    if total > 0 and debtor_vendor_id:
        lines.append(_vendor_line(
            debtor_vendor_id, "Dr", total,
            project_code=sb.project_code,
            narration=f"Customer receivable: SB {sb.sale_bill_no}",
        ))

    # Cr Revenue per item
    for item in sb.items:
        amt = _d(item.basic_amount)
        if amt > 0:
            lines.append(_cc_line(
                item.cc_code, "Cr", amt,
                project_code=sb.project_code,
                source_line_id=item.id,
                narration=f"SB revenue: {item.cc_code}",
            ))

    # Cr GST Output
    for gst in sb.gst_lines:
        if gst.is_selected and _d(gst.gst_amount) > 0:
            lines.append(_cc_line(
                gst.cc_code, "Cr", _d(gst.gst_amount),
                project_code=sb.project_code,
                gst_type=gst.gst_type,
                gst_rate=_d(gst.percent),
                source_line_id=gst.id,
                narration=f"GST Output {gst.gst_type}",
            ))

    header = {
        "posting_date": sb.invoice_date,
        "voucher_no": sb.sale_bill_no,
        "project_code": sb.project_code,
        "remarks": None,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 7. Sale Receipt Billing (SRB) — settles customer receivable
# ---------------------------------------------------------------------------

def _post_sale_receipt_billing(source_id):
    from app.models.saleReceiptBilling import SaleReceiptBillingMaster
    from app.models.saleReceipt import SaleReceiptMaster
    from app.models.ogSaleOrder import OgSaleOrderMaster

    srb = SaleReceiptBillingMaster.query.get(source_id)
    if not srb:
        from .posting_engine import PostingError
        raise PostingError(f"SaleReceiptBilling {source_id} not found")

    lines = []
    total = _d(srb.total_invoice_amount)

    # Bank/Cash from parent SaleReceipt
    receipt = SaleReceiptMaster.query.get(srb.receipt_id) if srb.receipt_id else None
    bank_cash_id = None
    if receipt:
        bank_cash_id = receipt.bank_ac_id if receipt.payment_mode == "Bank" else receipt.cash_ac_id

    if total > 0 and bank_cash_id:
        lines.append(_bank_line(
            bank_cash_id, "Dr", total,
            project_code=srb.project_code,
            narration=f"SRB receipt: {srb.srb_no}",
        ))

    # Cr Customer (debtor) via og_sale_order
    debtor_vendor_id = None
    if srb.og_sale_order_id:
        so = OgSaleOrderMaster.query.get(srb.og_sale_order_id)
        if so:
            debtor_vendor_id = so.debtor_id

    if total > 0 and debtor_vendor_id:
        lines.append(_vendor_line(
            debtor_vendor_id, "Cr", total,
            project_code=srb.project_code,
            narration=f"Customer receipt: SRB {srb.srb_no}",
        ))

    header = {
        "posting_date": srb.srb_date or (receipt.entry_date if receipt else None),
        "voucher_no": srb.srb_no,
        "project_code": srb.project_code,
        "remarks": None,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 8. Journal Entry (skip bulk_docket to avoid triple-posting with PCDV)
# ---------------------------------------------------------------------------

def _post_journal_entry(source_id):
    from app.models.journalEntry import JournalEntryMaster

    je = JournalEntryMaster.query.get(source_id)
    if not je:
        from .posting_engine import PostingError
        raise PostingError(f"JournalEntry {source_id} not found")

    # C12: Skip bulk_docket entries — PCDV is the authoritative source
    if je.entry_mode == "bulk_docket":
        return None, []

    lines = []

    for jel in je.lines:
        if jel.account_type == "CC" and jel.cc_id:
            if _d(jel.debit_amount) > 0:
                lines.append({
                    "account_type": "CC",
                    "cc_id": jel.cc_id,
                    "dr_cr": "Dr",
                    "amount": _d(jel.debit_amount),
                    "project_code": je.project_code,
                    "source_line_id": jel.id,
                    "narration": f"JE: {je.voucher_no}",
                })
            if _d(jel.credit_amount) > 0:
                lines.append({
                    "account_type": "CC",
                    "cc_id": jel.cc_id,
                    "dr_cr": "Cr",
                    "amount": _d(jel.credit_amount),
                    "project_code": je.project_code,
                    "source_line_id": jel.id,
                    "narration": f"JE: {je.voucher_no}",
                })

        elif jel.account_type == "Vendor" and jel.vendor_id:
            if _d(jel.debit_amount) > 0:
                lines.append(_vendor_line(
                    jel.vendor_id, "Dr", _d(jel.debit_amount),
                    project_code=je.project_code,
                    source_line_id=jel.id,
                    narration=f"JE: {je.voucher_no}",
                ))
            if _d(jel.credit_amount) > 0:
                lines.append(_vendor_line(
                    jel.vendor_id, "Cr", _d(jel.credit_amount),
                    project_code=je.project_code,
                    source_line_id=jel.id,
                    narration=f"JE: {je.voucher_no}",
                ))

        elif jel.account_type == "Customer":
            # customer_ref is free-text; post as CC to a Sundry Debtors account
            # (JE customer lines have no FK — best effort)
            if _d(jel.debit_amount) > 0:
                lines.append(_cc_line(
                    "CASD", "Dr", _d(jel.debit_amount),
                    project_code=je.project_code,
                    source_line_id=jel.id,
                    narration=f"JE customer: {jel.customer_ref or ''}",
                ))
            if _d(jel.credit_amount) > 0:
                lines.append(_cc_line(
                    "CASD", "Cr", _d(jel.credit_amount),
                    project_code=je.project_code,
                    source_line_id=jel.id,
                    narration=f"JE customer: {jel.customer_ref or ''}",
                ))

    header = {
        "posting_date": je.entry_date,
        "voucher_no": je.voucher_no,
        "project_code": je.project_code,
        "remarks": je.remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 9. Contra Entry
# ---------------------------------------------------------------------------

def _post_contra_entry(source_id):
    from app.models.contraEntry import ContraEntryMaster

    ce = ContraEntryMaster.query.get(source_id)
    if not ce:
        from .posting_engine import PostingError
        raise PostingError(f"ContraEntry {source_id} not found")

    lines = []

    for line in ce.lines:
        if line.dr_cr == "Dr" and _d(line.debit_amount) > 0:
            lines.append(_bank_line(
                line.account_id, "Dr", _d(line.debit_amount),
                project_code=ce.project_code,
                source_line_id=line.id,
                narration=f"CE transfer: {ce.voucher_no}",
            ))
        elif line.dr_cr == "Cr" and _d(line.credit_amount) > 0:
            lines.append(_bank_line(
                line.account_id, "Cr", _d(line.credit_amount),
                project_code=ce.project_code,
                source_line_id=line.id,
                narration=f"CE transfer: {ce.voucher_no}",
            ))

    header = {
        "posting_date": ce.entry_date,
        "voucher_no": ce.voucher_no,
        "project_code": ce.project_code,
        "remarks": ce.remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 10. Debit Note — reduces vendor payable
# ---------------------------------------------------------------------------

def _post_debit_note(source_id):
    from app.models.debitNote import DebitNoteMaster

    dn = DebitNoteMaster.query.get(source_id)
    if not dn:
        from .posting_engine import PostingError
        raise PostingError(f"DebitNote {source_id} not found")

    lines = []

    # Dr Vendor (reduce payable)
    total = _d(dn.total_amount)
    if total > 0 and dn.vendor_id:
        lines.append(_vendor_line(
            dn.vendor_id, "Dr", total,
            project_code=dn.project_code,
            narration=f"DN vendor adjustment: {dn.debit_note_no}",
        ))

    # Cr CC-code (expense reversal) per item
    for item in dn.items:
        amt = _d(item.basic_amount)
        if amt > 0:
            lines.append(_cc_line(
                item.cc_code, "Cr", amt,
                project_code=dn.project_code,
                source_line_id=item.id,
                narration=f"DN expense reversal: {item.cc_code}",
            ))

    # Cr GST Input reversal
    for gst in dn.gst_lines:
        if gst.is_selected and _d(gst.gst_amount) > 0:
            lines.append(_cc_line(
                gst.cc_code, "Cr", _d(gst.gst_amount),
                project_code=dn.project_code,
                gst_type=gst.gst_type,
                source_line_id=gst.id,
                narration=f"DN GST reversal {gst.gst_type}",
            ))

    header = {
        "posting_date": dn.entry_date,
        "voucher_no": dn.debit_note_no,
        "project_code": dn.project_code,
        "remarks": dn.remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 11. Credit Note — reduces customer receivable
# ---------------------------------------------------------------------------

def _post_credit_note(source_id):
    from app.models.creditNote import CreditNoteMaster

    cn = CreditNoteMaster.query.get(source_id)
    if not cn:
        from .posting_engine import PostingError
        raise PostingError(f"CreditNote {source_id} not found")

    lines = []

    # Dr CC-code (revenue reversal) per item
    for item in cn.items:
        amt = _d(item.basic_amount)
        if amt > 0:
            lines.append(_cc_line(
                item.cc_code, "Dr", amt,
                project_code=cn.project_code,
                source_line_id=item.id,
                narration=f"CN revenue reversal: {item.cc_code}",
            ))

    # Dr GST Output reversal
    for gst in cn.gst_lines:
        if gst.is_selected and _d(gst.gst_amount) > 0:
            lines.append(_cc_line(
                gst.cc_code, "Dr", _d(gst.gst_amount),
                project_code=cn.project_code,
                gst_type=gst.gst_type,
                source_line_id=gst.id,
                narration=f"CN GST reversal {gst.gst_type}",
            ))

    # Cr Customer (reduce receivable) — vendor_id IS the customer (debtor)
    total = _d(cn.total_amount)
    if total > 0 and cn.vendor_id:
        lines.append(_vendor_line(
            cn.vendor_id, "Cr", total,
            project_code=cn.project_code,
            narration=f"CN customer adjustment: {cn.credit_note_no}",
        ))

    header = {
        "posting_date": cn.entry_date,
        "voucher_no": cn.credit_note_no,
        "project_code": cn.project_code,
        "remarks": cn.remarks,
    }
    return header, lines


# ---------------------------------------------------------------------------
# 12. Petty Cash Docket Voucher
# ---------------------------------------------------------------------------

def _post_petty_cash_docket(source_id):
    from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher

    pcdv = PettyCashDocketVoucher.query.get(source_id)
    if not pcdv:
        from .posting_engine import PostingError
        raise PostingError(f"PCDV {source_id} not found")

    lines = []

    for detail in pcdv.details:
        amt = _d(detail.amount)
        if amt > 0:
            lines.append(_cc_line(
                detail.cc_code, "Dr", amt,
                project_code=pcdv.project_code,
                source_line_id=detail.id,
                narration=f"PCDV expense: {detail.cc_code}",
            ))

    total = _d(pcdv.total_amount)
    if total > 0 and pcdv.bank_cash_id:
        lines.append(_bank_line(
            pcdv.bank_cash_id, "Cr", total,
            project_code=pcdv.project_code,
            narration=f"PCDV payment: {pcdv.voucher_no}",
        ))

    header = {
        "posting_date": pcdv.voucher_date,
        "voucher_no": pcdv.voucher_no,
        "project_code": pcdv.project_code,
        "remarks": None,
    }
    return header, lines


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _post_grn(source_id):
    from .stock_posting_rules import post_grn_accounting
    return post_grn_accounting(source_id)


def _post_gin(source_id):
    from .stock_posting_rules import post_gin_accounting
    return post_gin_accounting(source_id)


_POSTING_RULES = {
    "purchase_bill": _post_purchase_bill,
    "payment_voucher": _post_payment_voucher,
    "bill_payment": _post_bill_payment_receipt,
    "sale_bill": _post_sale_bill,
    "sale_receipt_billing": _post_sale_receipt_billing,
    "journal_entry": _post_journal_entry,
    "contra_entry": _post_contra_entry,
    "debit_note": _post_debit_note,
    "credit_note": _post_credit_note,
    "petty_cash_docket": _post_petty_cash_docket,
    "grn": _post_grn,
    "gin": _post_gin,
}


def get_posting_rules(source_type):
    return _POSTING_RULES.get(source_type)


# All supported source types
SOURCE_TYPES = list(_POSTING_RULES.keys())
