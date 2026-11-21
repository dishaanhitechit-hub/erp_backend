"""
Undo a final approval — the engine behind reback requests.

A fully approved record can be sent back to its creator as long as nothing
has been made from it yet — the same "used further on?" rule that delete uses
(delete_manager.dependency_map), plus a few links delete does not cover.

What final approval did is undone in the same transaction:
  * accounting posting is REVERSED, not deleted (reversal_service) — the
    original + reversal stay in the ledger; re-approval posts a fresh entry
  * GRN / GIN stock rows are removed (only allowed while they are the latest
    movement for those items, so running balances stay right)
  * expense docket: its bank line goes from Reconciled back to reserved
  * logistics bill: the "posted to AP" marker is cleared
Then the record is put back exactly like a normal reback of that module
(status, unlock, level), approval fields are cleared, and a REBACK history
row is added with the remarks.

Who may ask / decide lives in reback_request.py (request -> final approver or
admin accepts).
"""

from datetime import datetime

from flask import current_app, g

from app.extensions import db

ADMIN_ROLES = ("admin", "super_admin")


# ==========================================
# REGISTRY
# key (same keys as bulk.BULK_MODULES) ->
#   model      "module.path:ClassName"
#   dep        delete_manager DEPENDENCY_MAP key (children + special checks)
#   extra      extra "used in" links: (model path, fk column, doc no field, label)
#   history    approval-history module code: str, or callable(record) -> str
#   posting    accounting source_type: str, or callable(record) -> str
#   stock      stock ledger source_type
#   status     status a normal reback sets (default "Reback")
#   reset      normal reback also sets current_level = 0
#   wa         module code for the WhatsApp "sent back" message
#   doc        doc number field
#   project    callable(record) -> project code (default record.project_code)
# ==========================================

def _brb_history(r):
    from app.modules.billing.constants import get_module_code
    return get_module_code(r.billing_type) or "billing_by_grn"


def _pr_history(r):
    from app.modules.billing.payment_request.service import _wf
    return _wf(r)


def _dc_project(r):
    from app.modules.resources.dc.service import _dc_project_code
    return _dc_project_code(r)


def _billing_history(r):
    return "sale_claim_bill" if r.mode == "sale_claim_bill" else "sale_certified_bill"


UNAPPROVE_MODULES = {
    # ── Resources
    "indent":          {"model": "app.models.indent_master:IndentMaster", "dep": "INDENT",
                        "history": "indent", "wa": "indent", "doc": "indent_no"},
    "order":           {"model": "app.models.orderMaster:OrderMaster", "dep": "ORDER",
                        "history": "order", "wa": "order", "doc": "order_no"},
    "pw_order":        {"model": "app.models.ORDER_projectwork:ProjectWorkOrderMaster", "dep": "PW_ORDER",
                        "history": "pw_order", "wa": "pw_order", "doc": "order_no"},
    "grn":             {"model": "app.models.grnMaster:GrnMaster", "dep": "GRN",
                        "history": "goods_received_note", "posting": "grn", "stock": "grn",
                        "wa": "grn", "doc": "grn_no"},
    "gin":             {"model": "app.models.ginMaster:GinMaster", "dep": "GIN",
                        "history": "goods_issue_note", "posting": "gin", "stock": "gin",
                        "wa": "gin", "doc": "gin_no"},
    "srn":             {"model": "app.models.srnMaster:SrnMaster", "dep": "SRN",
                        "history": "service_received_note", "wa": "srn", "doc": "srn_no"},
    "dc":              {"model": "app.models.dcMaster:DcMaster", "dep": "DC",
                        "history": "delivery_challan", "wa": "dc", "doc": "dc_no", "project": _dc_project},
    "bvs":             {"model": "app.models.bvsMaster:BvsMaster", "dep": "BVS",
                        "history": "billing_by_grn", "wa": "bvs", "doc": "bvs_no"},
    "bss":             {"model": "app.models.bssMaster:BssMaster", "dep": "BSS",
                        "history": "billing_by_srn", "wa": "bss", "doc": "bss_no"},
    "log_book":        {"model": "app.models.machineryLogBook:MachineryLogBook",
                        "extra": [("app.models.machineryLogBook:LogBookEntry", "log_book_id", "log_uid",
                                   "Log Book Entry")],
                        "history": "log_sheet", "doc": "log_book_no"},
    "log_entry":       {"model": "app.models.machineryLogBook:LogBookEntry",
                        "history": "log_sheet", "doc": "log_uid"},
    "batching":        {"model": "app.models.batchingPlant:BatchingPlantMaster", "dep": "BATCHING_PLANT",
                        "history": "batching", "wa": "batching_plant", "doc": "despatch_no"},
    "dlr":             {"model": "app.models.dlrMaster:DlrMaster", "dep": "DLR",
                        "history": "dlr", "status": "Rebacked", "reset": True, "wa": "dlr", "doc": "dlr_no"},
    # ── Logistics
    "transit_request": {"model": "app.models.transitRequest:TransitRequest", "dep": "TR",
                        "history": "transit_request", "status": "Correction", "reset": True, "doc": "tr_no"},
    "logistics_bill":  {"model": "app.models.logisticsBill:LogisticsBill", "dep": "LB",
                        "history": "logistics_bill", "status": "Correction", "reset": True, "doc": "lb_no"},
    # ── Sub-contractor billing
    "brr":             {"model": "app.models.brrMaster:BrrMaster", "dep": "BRR",
                        "history": "bill_receive_register", "wa": "brr", "doc": "brr_no"},
    "brb":             {"model": "app.models.brbMaster:BrbMaster", "dep": "BRB",
                        "history": _brb_history, "wa": "brb", "doc": "brb_no"},
    "payment_request": {"model": "app.models.paymentRequest:PaymentRequestMaster", "dep": "PAYMENT_REQUEST",
                        "history": _pr_history, "doc": "pr_no"},
    # ── Finance
    "sale_bill":       {"model": "app.models.saleBill:SaleBillMaster", "dep": "SALE_BILL",
                        "extra": [("app.models.creditNote:CreditNoteMaster", "sale_bill_id", "credit_note_no",
                                   "Credit Note")],
                        "history": "sale", "posting": "sale_bill", "wa": "sale_bill"},
    "purchase_bill":   {"model": "app.models.purchaseBill:PurchaseBillMaster", "dep": "PURCHASE_BILL",
                        "history": "purchases", "posting": "purchase_bill", "wa": "purchase_bill"},
    "sale_receipt_billing": {"model": "app.models.saleReceiptBilling:SaleReceiptBillingMaster",
                        "dep": "SALE_RECEIPT_BILLING", "history": "receipt", "posting": "sale_receipt_billing"},
    "debit_note":      {"model": "app.models.debitNote:DebitNoteMaster", "dep": "DEBIT_NOTE",
                        "history": "debit_note", "posting": "debit_note"},
    "credit_note":     {"model": "app.models.creditNote:CreditNoteMaster", "dep": "CREDIT_NOTE",
                        "history": "credit_note", "posting": "credit_note"},
    "payment_voucher": {"model": "app.models.paymentVoucher:PaymentVoucherMaster", "dep": "PAYMENT_VOUCHER",
                        "history": "payment", "posting": "payment_voucher", "wa": "payment_voucher"},
    "bill_payment":    {"model": "app.models.billPaymentReceipt:BillPaymentReceiptMaster", "dep": "BILL_PAYMENT",
                        "history": "payment", "posting": "bill_payment", "wa": "bill_payment_receipt"},
    "contra_entry":    {"model": "app.models.contraEntry:ContraEntryMaster", "dep": "CONTRA_ENTRY",
                        "history": "contra", "posting": "contra_entry"},
    "journal_entry":   {"model": "app.models.journalEntry:JournalEntryMaster", "dep": "JOURNAL_ENTRY",
                        "extra": [("app.models.billPaymentReceipt:BillPaymentReceiptMaster", "journal_entry_id",
                                   "receipt_no", "Bill Payment")],
                        "history": "journal", "posting": "journal_entry"},
    "journal_voucher": {"model": "app.models.journalVoucher:PettyCashJournalVoucher",
                        "checks": ["jv_linked_journal"], "history": "petty_cash", "doc": "voucher_no"},
    "petty_cash_budget": {"model": "app.models.pettyCashBudget:PettyCashBudget", "dep": "PETTY_CASH_BUDGET",
                        "history": "petty_cash"},
    "petty_cash_docket": {"model": "app.models.pettyCashDocketVoucher:PettyCashDocketVoucher",
                        "dep": "PETTY_CASH_VOUCHER",
                        "extra": [("app.models.journalVoucher:PettyCashJournalLine", "docket_voucher_id",
                                   "journal_voucher_id", "Journal Voucher")],
                        "history": "petty_cash", "posting": "petty_cash_docket", "bank_line": True,
                        "doc": "voucher_no"},
    # ── Project management
    "project_billing": {"model": "app.models.billingMaster:BillingMaster", "dep": "BILLING",
                        "history": _billing_history, "posting": lambda r: r.mode, "wa": "billing"},
    "og_sale_order":   {"model": "app.models.ogSaleOrder:OgSaleOrderMaster", "dep": "OG_SALE_ORDER",
                        "history": "sale_order", "wa": "og_sale_order"},
    "contract_budget": {"model": "app.models.budget:BudgetMaster", "history": "budget_master",
                        "wa": "budget", "doc": "budget_no"},
    "uncertain_allocation": {"model": "app.models.uncertainAllocation:UncertainAllocationMaster",
                        "dep": "UNCERTAIN_ALLOCATION", "history": "sale_claim_bill",
                        "posting": "uncertified_statement"},
    "dpr":             {"model": "app.models.siteReport:DailyProgressReport",
                        "history": "daily_progress_report", "doc": "dpr_no"},
    "drawing_register": {"model": "app.models.drawingRegister:DrawingRegister", "dep": "DRAWING_REGISTER",
                        "history": "drawing_register", "wa": "drawing_register"},
    "concrete_registry": {"model": "app.models.concrete_registry:ConcreteRegistry", "dep": "CONCRETE_REGISTRY",
                        "history": "concrete_register", "wa": "concrete_registry",
                        "project": lambda r: r.projectcode},
    "hindrance_register": {"model": "app.models.hindranceRegister:HindranceRegister",
                        "dep": "HINDRANCE_REGISTER", "history": "hindrance_register", "wa": "hindrance_register"},
    "bbs_register":    {"model": "app.models.bbsRegister:BbsRegister", "dep": "BBS_REGISTER",
                        "history": "bbs_register", "wa": "bbs_register"},
}


def _labels():
    from .bulk import BULK_MODULES
    return {k: v["label"] for k, v in BULK_MODULES.items()}


class Blocked(Exception):
    """The record can't be sent back; message says why."""


# ==========================================
# HELPERS
# ==========================================

def _load(path):
    import importlib
    mod, name = path.split(":")
    return getattr(importlib.import_module(mod), name)


def _value(spec, record):
    return spec(record) if callable(spec) else spec


def is_admin():
    user = g.get("current_user") or {}
    return user.get("role") in ADMIN_ROLES


def _user_id():
    user = g.get("current_user") or {}
    try:
        return int(user.get("id"))
    except (TypeError, ValueError):
        return None


def _dep_config(entry):
    if not entry.get("dep"):
        return None
    from app.modules.delete_manager.dependency_map import DEPENDENCY_MAP
    return DEPENDENCY_MAP.get(entry["dep"])


def _project(entry, record):
    fn = entry.get("project")
    return fn(record) if fn else record.project_code


def _doc_no(entry, record):
    field = entry.get("doc") or (_dep_config(entry) or {}).get("doc_no_field")
    return str(getattr(record, field, None) or record.id) if field else str(record.id)


# ==========================================
# "USED FURTHER ON?" — same as delete, plus a few links
# ==========================================

def _check_lb_posted(record):
    # approval puts a negative marker (-id); a positive id is a real journal
    if record.voucher_id and record.voucher_id > 0:
        return [f"Posted to Finance (voucher #{record.voucher_id}) — reverse it first"]
    return []


def _check_jv_linked_journal(record):
    if record.linked_journal_id:
        from app.models.journalEntry import JournalEntryMaster
        je = JournalEntryMaster.query.get(record.linked_journal_id)
        return [f"Journal Entry {getattr(je, 'voucher_no', None) or record.linked_journal_id}"]
    return []


_CHECKS = {"jv_linked_journal": _check_jv_linked_journal}


def find_blockers(key, record):
    """Documents made from this record (each as 'Label DOC-NO')."""
    entry = UNAPPROVE_MODULES[key]
    found = []

    config = _dep_config(entry)
    if config:
        from app.modules.delete_manager.service import _check_children
        checks = list(config.get("special_checks", []))
        if key == "logistics_bill":
            # LB approval itself sets the AP marker — judged separately below
            config = {**config, "special_checks": [c for c in checks if c != "lb_posted_to_finance"]}
        for b in _check_children(entry["dep"], record.id, config):
            label = b["label"].split(" — ")[0].split(" (")[0]
            found.append(f"{label} {b['doc_no']}")

    for path, fk, doc_field, label in entry.get("extra", []):
        model = _load(path)
        rows = model.query.filter(getattr(model, fk) == record.id).all()
        nos = sorted({str(getattr(r, doc_field, None) or r.id) for r in rows})
        if label == "Journal Voucher" and nos:
            from app.models.journalVoucher import PettyCashJournalVoucher
            jvs = PettyCashJournalVoucher.query.filter(PettyCashJournalVoucher.id.in_([int(n) for n in nos])).all()
            nos = sorted({jv.voucher_no or str(jv.id) for jv in jvs})
        found.extend(f"{label} {n}" for n in nos)

    for name in entry.get("checks", []):
        found.extend(_CHECKS[name](record))
    if key == "logistics_bill":
        found.extend(_check_lb_posted(record))

    # keep order, drop repeats
    return list(dict.fromkeys(found))


def _posting_rows(source_type, record_id):
    from app.models.accounting import AccountingLedger
    return AccountingLedger.query.filter_by(source_type=source_type, source_id=record_id).all()


def _stock_rows(source_type, record_id):
    from app.models.stockLedger import StockLedger
    return StockLedger.query.filter_by(source_type=source_type, source_id=record_id).all()


def _check_ledgers(entry, record):
    """Locked financial year / later stock movement. Returns reasons."""
    reasons = []
    posting = _value(entry.get("posting"), record)
    if posting:
        for row in _posting_rows(posting, record.id):
            fy = row.financial_year
            if fy is not None and fy.is_locked:
                reasons.append(f"Financial year {fy.fy_code} is locked")
                break

    stock = entry.get("stock")
    if stock:
        from app.models.stockLedger import StockLedger
        rows = _stock_rows(stock, record.id)
        if rows:
            last_id = max(r.id for r in rows)
            keys = {(r.item_id, r.project_code, r.location_id) for r in rows}
            for item_id, project_code, location_id in keys:
                later = StockLedger.query.filter(
                    StockLedger.item_id == item_id,
                    StockLedger.project_code == project_code,
                    StockLedger.location_id == location_id,
                    StockLedger.id > last_id,
                    db.or_(StockLedger.source_type != stock, StockLedger.source_id != record.id),
                ).first()
                if later:
                    reasons.append(f"Stock of {later.item_code or 'an item'} has moved since "
                                   f"({later.source_type.upper()} #{later.source_id})")
                    break
    return reasons


def check_record(key, record_id, lock=False):
    """(record, None) when it can be sent back, else (record_or_None, reason).
    lock=True takes a row-level FOR UPDATE lock (used by accept_request)."""
    entry = UNAPPROVE_MODULES.get(key)
    if not entry:
        return None, f"Unknown module: {key}"
    model = _load(entry["model"])
    if lock:
        # lock the bare row only: FOR UPDATE over a model with lazy="joined"
        # relationships (e.g. OrderMaster) fails on Postgres (outer join)
        db.session.query(model.id).filter(model.id == record_id).with_for_update().first()
        record = model.query.populate_existing().get(record_id)
    else:
        record = model.query.get(record_id)
    if not record:
        return None, "Record not found"
    if (record.workflow_status or "") != "Approved":
        return record, "Only fully approved records can be sent back this way"

    blockers = find_blockers(key, record)
    if blockers:
        shown = ", ".join(blockers[:10]) + (f" and {len(blockers) - 10} more" if len(blockers) > 10 else "")
        return record, f"Used in {shown}. Reback or delete those first."

    reasons = _check_ledgers(entry, record)
    if reasons:
        return record, reasons[0]
    return record, None


# ==========================================
# UNDO FINAL APPROVAL
# ==========================================

def _unreconcile_bank_line(record, user_id):
    from app.models.bankStatement import BankTransaction
    from app.modules.finance.bank_statement.service import _audit
    t = BankTransaction.query.filter_by(linked_docket_id=record.id).with_for_update().first()
    if t and t.reconciliation_status == "Reconciled":
        t.reconciliation_status = "Unreconciled"   # still linked = reserved
        t.reconciled_by = None
        t.reconciled_at = None
        _audit(t, "UNRECONCILE", user_id, record, "Docket sent back after approval")


def _send_whatsapp(entry, record, user_id, remarks):
    wa_code = entry.get("wa")
    if not wa_code:
        return
    try:
        from app.models.user import User
        from app.modules.communication import whatsapp_events as wa
        uuid_attr = next((c.key for c in record.__table__.columns if c.key.endswith("uuid")), None)
        actor = User.query.get(user_id)
        wa.on_reback(
            module_code=wa_code,
            doc_no=_doc_no(entry, record),
            uuid=str(getattr(record, uuid_attr)) if uuid_attr else "",
            project_code=_project(entry, record),
            approver_name=actor.username if actor else str(user_id),
            creator_user=User.query.get(record.created_by) if getattr(record, "created_by", None) else None,
            comments=remarks,
            record_id=record.id,
        )
    except Exception:  # message failure never undoes the reback
        current_app.logger.exception("Reback-after-approval WhatsApp failed")


def _apply(key, record, user_id, remarks):
    """Undo approval + put the record back for correction. Caller commits."""
    entry = UNAPPROVE_MODULES[key]
    now = datetime.utcnow()

    # Accounting: never delete ledger rows — post a reversal (central accounting).
    # The original is flagged is_reversed, so re-approval posts a fresh entry.
    from app.modules.finance.accounting.reversal_service import reverse_for_reback
    reverse_for_reback(entry, record, user_id, remarks)
    # Stock rows are still removed (allowed only while they are the latest
    # movement — see _check_ledgers), so re-approval can post stock again.
    if entry.get("stock"):
        for row in sorted(_stock_rows(entry["stock"], record.id), key=lambda r: r.id, reverse=True):
            db.session.delete(row)
    if entry.get("bank_line"):
        _unreconcile_bank_line(record, user_id)
    if key == "logistics_bill" and record.voucher_id and record.voucher_id < 0:
        record.voucher_id = None

    level = record.current_level
    record.workflow_status = entry.get("status", "Reback")
    if entry.get("reset"):
        record.current_level = 0
    for attr, value in (("locked", False), ("approved_by", None), ("final_approved_at", None),
                        ("correction_sent_at", now), ("updated_by", user_id), ("updated_at", now)):
        if hasattr(record, attr):
            setattr(record, attr, value)

    from app.modules.work_flow import create_history
    create_history(
        project_code=_project(entry, record),
        module_code=_value(entry["history"], record),
        record_id=record.id,
        level_no=level,
        action="REBACK",
        action_by=user_id,
        comments=remarks,
    )


# ==========================================
# HELPERS FOR ROUTES
# ==========================================

def _int(v):
    try:
        i = int(v)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def module_for_path(path):
    """Registry key from a module's my-approval-status URL (what view pages already know)."""
    from .bulk import BULK_MODULES
    path = (path or "").split("?", 1)[0].rstrip("/")
    for key, entry in sorted(BULK_MODULES.items(), key=lambda kv: -len(kv[1]["prefix"])):
        if path.endswith(f"{entry['prefix']}/my-approval-status"):
            return key
    return None
