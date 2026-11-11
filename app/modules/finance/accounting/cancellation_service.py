"""
Document Cancellation Service.

Handles the accounting-safe cancellation of approved/posted documents.
Instead of deleting source documents or accounting entries, this service:

1. Creates a reversal posting (opposite Dr/Cr) linked to the original
2. Marks the source document as Cancelled with audit info
3. Prevents duplicate reversals

For document correction: cancel first, then create a new document
through the normal approval workflow.
"""

from datetime import datetime

from app.extensions import db
from app.models.accounting import AccountingLedger
from .posting_engine import reverse_posting, PostingError
from .deletion_guard import is_posted, is_reversed, _SOURCE_TYPE_MAP


def cancel_posted_document(source_type, source_id, user_id, reason=None):
    """
    Cancel a posted document by creating a reversal entry.

    Returns (response_dict, status_code).

    Steps:
      1. Verify the document is posted
      2. Verify it hasn't already been reversed
      3. Create the reversal posting
      4. Mark the source document as Cancelled (if it has that field)
      5. Record audit info
    """
    if source_type not in _SOURCE_TYPE_MAP.values():
        return {"message": f"Unknown source_type: {source_type}"}, 400

    if not is_posted(source_type, source_id):
        return {"message": "Document has not been posted. Nothing to cancel."}, 400

    if is_reversed(source_type, source_id):
        return {"message": "Document has already been cancelled/reversed."}, 409

    try:
        reversal = reverse_posting(source_type, source_id, user_id)
        if reversal is None:
            return {"message": "Reversal could not be created (already reversed or not posted)."}, 409

        if reason:
            reversal.remarks = f"Cancellation: {reason}"

        if source_type in ("grn", "gin"):
            try:
                from .stock_ledger_service import reverse_stock_entry
                reverse_stock_entry(source_type, source_id, user_id)
            except Exception:
                pass

        _mark_source_cancelled(source_type, source_id, user_id, reason)

        db.session.commit()

        return {
            "message": "Document cancelled successfully. Reversal posting created.",
            "data": {
                "reversalId": reversal.id,
                "reversalVoucherNo": reversal.voucher_no,
                "originalSourceType": source_type,
                "originalSourceId": source_id,
                "cancelledBy": user_id,
                "cancelledAt": datetime.utcnow().isoformat(),
                "reason": reason,
            },
        }, 200

    except PostingError as e:
        db.session.rollback()
        return {"message": f"Cancellation failed: {str(e)}"}, 500
    except Exception as e:
        db.session.rollback()
        return {"message": f"Cancellation failed: {str(e)}"}, 500


def _mark_source_cancelled(source_type, source_id, user_id, reason):
    """
    Try to set workflow_status = 'Cancelled' on the source document.
    This is best-effort — if the model doesn't have workflow_status,
    the accounting reversal alone is sufficient.
    """
    model_map = {
        "purchase_bill": ("app.models.purchaseBill", "PurchaseBillMaster"),
        "payment_voucher": ("app.models.paymentVoucher", "PaymentVoucherMaster"),
        "bill_payment": ("app.models.billPaymentReceipt", "BillPaymentReceiptMaster"),
        "sale_bill": ("app.models.saleBill", "SaleBillMaster"),
        "sale_receipt_billing": ("app.models.saleReceiptBilling", "SaleReceiptBillingMaster"),
        "journal_entry": ("app.models.journalEntry", "JournalEntryMaster"),
        "contra_entry": ("app.models.contraEntry", "ContraEntryMaster"),
        "debit_note": ("app.models.debitNote", "DebitNoteMaster"),
        "credit_note": ("app.models.creditNote", "CreditNoteMaster"),
        "petty_cash_docket": ("app.models.pettyCashDocketVoucher", "PettyCashDocketVoucher"),
        "grn": ("app.models.grnMaster", "GrnMaster"),
        "gin": ("app.models.ginMaster", "GinMaster"),
    }

    entry = model_map.get(source_type)
    if not entry:
        return

    module_path, class_name = entry
    try:
        import importlib
        mod = importlib.import_module(module_path)
        Model = getattr(mod, class_name)
        doc = Model.query.get(source_id)
        if doc and hasattr(doc, "workflow_status"):
            doc.workflow_status = "Cancelled"
        if doc and hasattr(doc, "cancelled_by"):
            doc.cancelled_by = user_id
        if doc and hasattr(doc, "cancelled_at"):
            doc.cancelled_at = datetime.utcnow()
        if doc and hasattr(doc, "cancellation_reason"):
            doc.cancellation_reason = reason
    except Exception:
        pass


def get_cancellation_info(source_type, source_id):
    """
    Return the cancellation/reversal status for a document.
    """
    original = AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=False,
    ).first()

    if not original:
        return {"posted": False, "reversed": False}, 200

    reversal = AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=True,
    ).first()

    return {
        "posted": True,
        "postingId": original.id,
        "voucherNo": original.voucher_no,
        "postingDate": original.posting_date.isoformat() if original.posting_date else None,
        "reversed": reversal is not None,
        "reversalId": reversal.id if reversal else None,
        "reversalVoucherNo": reversal.voucher_no if reversal else None,
        "reversedAt": reversal.created_at.isoformat() if reversal and reversal.created_at else None,
        "reversedBy": reversal.created_by if reversal else None,
    }, 200
