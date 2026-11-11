"""
Safe historical posting for existing approved documents.

Posts all approved documents to the central accounting ledger in
dependency order, skipping already-posted and bulk_docket JEs.
"""

import logging
from sqlalchemy import inspect as sa_inspect
from app.extensions import db
from app.models.accounting import AccountingLedger
from .posting_engine import post_document, PostingError

logger = logging.getLogger(__name__)


def _table_exists(table_name):
    """Check if a table exists in the current database."""
    try:
        return sa_inspect(db.engine).has_table(table_name)
    except Exception:
        return False

# Posting order: liabilities/receivables first, then settlements
_POSTING_ORDER = [
    ("journal_entry", "JournalEntryMaster", "journal_entry_master", "workflow_status", "entry_date"),
    ("purchase_bill", "PurchaseBillMaster", "purchase_bill_master", "workflow_status", "processing_date"),
    ("sale_bill", "SaleBillMaster", "sale_bill_master", "workflow_status", "invoice_date"),
    ("payment_voucher", "PaymentVoucherMaster", "payment_voucher_master", "workflow_status", "payment_date"),
    ("petty_cash_docket", "PettyCashDocketVoucher", "petty_cash_docket_voucher", "workflow_status", "voucher_date"),
    ("bill_payment", "BillPaymentReceiptMaster", "bill_payment_receipt_master", "workflow_status", "payment_date"),
    ("sale_receipt_billing", "SaleReceiptBillingMaster", "sale_receipt_billing", "workflow_status", "srb_date"),
    ("debit_note", "DebitNoteMaster", "debit_note_master", "workflow_status", "entry_date"),
    ("credit_note", "CreditNoteMaster", "credit_note_master", "workflow_status", "entry_date"),
    ("contra_entry", "ContraEntryMaster", "contra_entry_master", "workflow_status", "entry_date"),
    ("grn", "GrnMaster", "grn_master", "workflow_status", "grn_date"),
    ("gin", "GinMaster", "gin_master", "workflow_status", "gin_date"),
]


def _get_model_class(model_name):
    """Import a model class by name."""
    if model_name == "PurchaseBillMaster":
        from app.models.purchaseBill import PurchaseBillMaster
        return PurchaseBillMaster
    elif model_name == "PaymentVoucherMaster":
        from app.models.paymentVoucher import PaymentVoucherMaster
        return PaymentVoucherMaster
    elif model_name == "BillPaymentReceiptMaster":
        from app.models.billPaymentReceipt import BillPaymentReceiptMaster
        return BillPaymentReceiptMaster
    elif model_name == "SaleBillMaster":
        from app.models.saleBill import SaleBillMaster
        return SaleBillMaster
    elif model_name == "SaleReceiptBillingMaster":
        from app.models.saleReceiptBilling import SaleReceiptBillingMaster
        return SaleReceiptBillingMaster
    elif model_name == "JournalEntryMaster":
        from app.models.journalEntry import JournalEntryMaster
        return JournalEntryMaster
    elif model_name == "ContraEntryMaster":
        from app.models.contraEntry import ContraEntryMaster
        return ContraEntryMaster
    elif model_name == "DebitNoteMaster":
        from app.models.debitNote import DebitNoteMaster
        return DebitNoteMaster
    elif model_name == "CreditNoteMaster":
        from app.models.creditNote import CreditNoteMaster
        return CreditNoteMaster
    elif model_name == "PettyCashDocketVoucher":
        from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher
        return PettyCashDocketVoucher
    elif model_name == "GrnMaster":
        from app.models.grnMaster import GrnMaster
        return GrnMaster
    elif model_name == "GinMaster":
        from app.models.ginMaster import GinMaster
        return GinMaster
    return None


def run_historical_posting(user_id, options=None):
    """
    Post all approved historical documents to the accounting ledger.
    Processes in dependency order with per-document error handling.
    """
    if not _table_exists("accounting_ledger"):
        return {"message": "accounting_ledger table does not exist. Please run the database migration first."}, 400
    if not _table_exists("accounting_ledger_lines"):
        return {"message": "accounting_ledger_lines table does not exist. Please run the database migration first."}, 400

    stock_table_ready = _table_exists("stock_ledger")

    options = options or {}
    dry_run = options.get("dry_run", False)
    batch_size = options.get("batch_size", 100)

    results = {
        "posted": {},
        "skipped": {},
        "errors": {},
        "summary": {},
    }

    for source_type, model_name, table_name, status_col, date_col in _POSTING_ORDER:
        if source_type in ("grn", "gin") and not stock_table_ready:
            results["skipped"][source_type] = 0
            results["errors"][source_type] = ["stock_ledger table not yet created — skipping GRN/GIN posting"]
            continue

        Model = _get_model_class(model_name)
        if not Model:
            results["errors"][source_type] = [f"Model {model_name} not found"]
            continue

        status_field = getattr(Model, status_col, None)
        if not status_field:
            results["errors"][source_type] = [f"No {status_col} field"]
            continue

        # Only approved, active documents
        q = Model.query.filter(status_field == "Approved")
        if hasattr(Model, "status"):
            q = q.filter(Model.status != "Deleted")

        date_field = getattr(Model, date_col, None)
        if date_field is not None:
            q = q.order_by(date_field.asc(), Model.id.asc())
        else:
            q = q.order_by(Model.id.asc())

        posted_count = 0
        skipped_count = 0
        error_list = []

        for doc in q.all():
            try:
                if dry_run:
                    # Check if already posted
                    existing = AccountingLedger.query.filter_by(
                        source_type=source_type,
                        source_id=doc.id,
                        is_reversal=False,
                    ).first()
                    if existing:
                        skipped_count += 1
                    else:
                        posted_count += 1
                    continue

                if source_type in ("grn", "gin"):
                    try:
                        from .stock_posting_rules import post_grn_stock, post_gin_stock
                        if source_type == "grn":
                            post_grn_stock(doc.id, user_id=user_id)
                        else:
                            post_gin_stock(doc.id, user_id=user_id)
                    except Exception:
                        pass

                result = post_document(source_type, doc.id, user_id)
                if result is None:
                    skipped_count += 1
                else:
                    posted_count += 1
                    if posted_count % batch_size == 0:
                        db.session.commit()

            except PostingError as e:
                error_list.append({"id": doc.id, "error": str(e)})
                db.session.rollback()
            except Exception as e:
                error_list.append({"id": doc.id, "error": str(e)})
                db.session.rollback()

        if not dry_run and posted_count > 0:
            db.session.commit()

        results["posted"][source_type] = posted_count
        results["skipped"][source_type] = skipped_count
        if error_list:
            results["errors"][source_type] = error_list

    total_posted = sum(results["posted"].values())
    total_skipped = sum(results["skipped"].values())
    total_errors = sum(len(v) if isinstance(v, list) else 0 for v in results["errors"].values())

    results["summary"] = {
        "totalPosted": total_posted,
        "totalSkipped": total_skipped,
        "totalErrors": total_errors,
        "dryRun": dry_run,
    }

    return {"message": "Historical posting complete", "data": results}, 200


def get_posting_status():
    """Report how many documents are posted vs pending per source type."""
    if not _table_exists("accounting_ledger"):
        return {"message": "accounting_ledger table does not exist. Please run the database migration first."}, 400

    stock_table_ready = _table_exists("stock_ledger")
    status = {}

    for source_type, model_name, table_name, status_col, date_col in _POSTING_ORDER:
        if source_type in ("grn", "gin") and not stock_table_ready:
            continue

        Model = _get_model_class(model_name)
        if not Model:
            continue

        status_field = getattr(Model, status_col, None)
        if not status_field:
            continue

        # Approved documents
        approved_q = Model.query.filter(status_field == "Approved")
        if hasattr(Model, "status"):
            approved_q = approved_q.filter(Model.status != "Deleted")
        total_approved = approved_q.count()

        # Already posted
        posted_count = AccountingLedger.query.filter_by(
            source_type=source_type,
            is_reversal=False,
        ).count()

        status[source_type] = {
            "totalApproved": total_approved,
            "posted": posted_count,
            "pending": max(0, total_approved - posted_count),
        }

    return {"message": "OK", "data": status}, 200
