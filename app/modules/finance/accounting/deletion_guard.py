"""
Accounting Deletion Guard.

Centralized safeguard that prevents physical deletion of source documents
that have been posted to the accounting ledger. Each module's delete
function should call `check_posted_before_delete()` before proceeding.

If a posted document needs cancellation, the caller must use the
cancellation workflow instead: reverse the accounting posting, then
mark the source document as Cancelled.
"""

from app.models.accounting import AccountingLedger

# Maps source document types to their posting engine source_type keys
_SOURCE_TYPE_MAP = {
    "PurchaseBillMaster": "purchase_bill",
    "PaymentVoucherMaster": "payment_voucher",
    "BillPaymentReceiptMaster": "bill_payment",
    "SaleBillMaster": "sale_bill",
    "SaleReceiptBillingMaster": "sale_receipt_billing",
    "JournalEntryMaster": "journal_entry",
    "ContraEntryMaster": "contra_entry",
    "DebitNoteMaster": "debit_note",
    "CreditNoteMaster": "credit_note",
    "PettyCashDocketVoucher": "petty_cash_docket",
    "GrnMaster": "grn",
    "GinMaster": "gin",
}


def is_posted(source_type, source_id):
    """Check if a document has been posted to the accounting ledger."""
    return AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=False,
    ).first() is not None


def is_reversed(source_type, source_id):
    """Check if a document's posting has already been reversed."""
    return AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=True,
    ).first() is not None


def check_posted_before_delete(model_class_name, doc_id):
    """
    Call from a module's delete function AFTER the locked check passes.
    Returns (can_delete: bool, message: str).

    If the document has been posted, physical deletion is blocked.
    The caller should return the message as a 400 error.
    """
    source_type = _SOURCE_TYPE_MAP.get(model_class_name)
    if not source_type:
        return True, ""

    if is_posted(source_type, doc_id):
        return False, (
            f"This {model_class_name} has been posted to the accounting ledger. "
            "It cannot be deleted. Use the cancellation workflow to reverse "
            "the accounting entry first."
        )

    return True, ""


def check_fy_has_postings(fy_id):
    """
    Prevent deletion of a FinancialYear that contains posted transactions.
    Returns (has_postings: bool, message: str).
    """
    count = AccountingLedger.query.filter_by(financial_year_id=fy_id).count()
    if count > 0:
        return True, (
            f"This financial year has {count} accounting entries. "
            "It cannot be deleted while posted transactions exist."
        )
    return False, ""
