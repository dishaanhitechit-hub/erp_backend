"""
Accounting Deletion Guard.

Rule: a document that is IN THE BOOKS (has an active posting) is never
physically deleted, and its ledger rows are never deleted either.

  * active posting  → block delete; the document must be cancelled
                      (reversal posting) — see reversal_service.cancel_document.
                      The delete manager does this automatically.
  * reversed only   → (rebacked, then edited) the document is no longer in the
                      books; the original + reversal pair stays in the ledger as
                      the audit trail and the draft itself may be deleted.
  * never posted    → delete freely.

Every module's own delete function calls `check_posted_before_delete()`;
the central delete manager calls `posting_source_for()` + `is_posted()`.
"""

from app.models.accounting import AccountingLedger

# Source document model → posting engine source_type.
# A callable takes the record (BillingMaster posts under its mode).
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
    "BillingMaster": lambda record: getattr(record, "mode", None),
    "UncertainAllocationMaster": "uncertified_statement",
}

# Every source_type that can be cancelled (reversed) as a document.
CANCELLABLE_SOURCE_TYPES = {
    "purchase_bill", "payment_voucher", "bill_payment", "sale_bill",
    "sale_receipt_billing", "journal_entry", "contra_entry", "debit_note",
    "credit_note", "petty_cash_docket", "grn", "gin",
    "sale_claim_bill", "sale_certified_bill", "uncertified_statement",
}


def source_type_of(model_class_name, record=None):
    spec = _SOURCE_TYPE_MAP.get(model_class_name)
    if callable(spec):
        return spec(record) if record is not None else None
    return spec


def is_posted(source_type, source_id):
    """True while the document is in the books (has an active posting)."""
    if not source_type:
        return False
    return AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=False,
        is_reversed=False,
    ).first() is not None


def was_ever_posted(source_type, source_id):
    """True if the document has any posting history (active or reversed)."""
    if not source_type:
        return False
    return AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
    ).first() is not None


def is_reversed(source_type, source_id):
    """True if at least one posting of the document has been reversed."""
    return AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=True,
    ).first() is not None


def posting_source_for(record):
    """source_type the record posts under (None = the model never posts)."""
    return source_type_of(type(record).__name__, record)


def check_posted_before_delete(model_class_name, doc_id, record=None):
    """
    Call from a module's delete function AFTER the locked check passes.
    Returns (can_delete: bool, message: str).
    """
    if record is None and callable(_SOURCE_TYPE_MAP.get(model_class_name)):
        return True, ""
    source_type = source_type_of(model_class_name, record)
    if not source_type:
        return True, ""

    if is_posted(source_type, doc_id):
        return False, (
            "This document is posted to the accounting ledger and cannot be deleted. "
            "Delete it from the Delete button (it will be cancelled with a reversal "
            "entry) or raise a reback request."
        )

    return True, ""


def cc_posting_count(cc_id):
    """Return number of accounting ledger line entries for a CC code."""
    from app.models.accounting import AccountingLedgerLine
    return AccountingLedgerLine.query.filter_by(
        account_type="CC", cc_id=cc_id
    ).count()


def cc_has_postings(cc_id):
    """Check if a CC code has any accounting ledger line entries."""
    return cc_posting_count(cc_id) > 0


def group_posting_count(group_id):
    """Return number of postings across all CC codes under a group."""
    from app.models.cc_code import CCCode
    from app.models.accounting import AccountingLedgerLine
    cc_ids = [c.id for c in CCCode.query.filter_by(group_id=group_id).all()]
    if not cc_ids:
        return 0
    return AccountingLedgerLine.query.filter(
        AccountingLedgerLine.account_type == "CC",
        AccountingLedgerLine.cc_id.in_(cc_ids),
    ).count()


def group_has_postings(group_id):
    """Check if any CC code under a group has accounting postings."""
    return group_posting_count(group_id) > 0


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
