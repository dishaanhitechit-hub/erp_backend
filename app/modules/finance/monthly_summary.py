"""
Finance module — monthly email summary.
Groups every document type by project_code.
"""
from datetime import datetime
from collections import defaultdict

from app.extensions import db
from app.models.project import Project
from app.models.purchaseBill import PurchaseBillMaster
from app.models.saleBill import SaleBillMaster
from app.models.purchaseVoucher import PurchaseVoucherMaster
from app.models.paymentVoucher import PaymentVoucherMaster
from app.models.journalEntry import JournalEntryMaster
from app.models.contraEntry import ContraEntryMaster
from app.models.creditNote import CreditNoteMaster
from app.models.debitNote import DebitNoteMaster
from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.saleReceipt import SaleReceiptMaster

from app.utils.email_template import (
    stat_row, section_header, project_block_open, table, no_data_note, build_email
)
from app.utils.date_utils import month_label, period_label, last_month_range
from app.utils.email_service import send_monthly_report
from flask import current_app


# ── helpers ──────────────────────────────────────────────────────────────────

def _project_map() -> dict:
    """Return {project_code: (project_name, client_name)}."""
    rows = db.session.query(
        Project.project_code, Project.project_name, Project.client_name
    ).all()
    return {r.project_code: (r.project_name or "", r.client_name or "") for r in rows}


def _group_by_project(rows, code_attr="project_code") -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[getattr(r, code_attr)].append(r)
    return groups


# ── per-document query helpers ────────────────────────────────────────────────

def _query(model, start, end):
    return (
        db.session.query(model)
        .filter(model.created_at >= start, model.created_at <= end)
        .all()
    )


# ── section renderers ─────────────────────────────────────────────────────────

def _render_purchase_bills(rows, proj_map):
    html = section_header("Purchase Bills")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([
                r.purchase_bill_no,
                str(r.processing_date) if r.processing_date else "—",
                r.workflow_status,
                r.total_invoice_amount,
            ])
            total_count += 1
            total_amt += float(r.total_invoice_amount or 0)
        html += table(["Bill No", "Date", "Status", "Amount"], table_rows, amount_cols={3})
    html = stat_row([("Total Bills", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_sale_bills(rows, proj_map):
    html = section_header("Sale Bills")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([
                r.sale_bill_no,
                str(r.processing_date) if r.processing_date else "—",
                r.workflow_status,
                r.total_invoice_amount,
            ])
            total_count += 1
            total_amt += float(r.total_invoice_amount or 0)
        html += table(["Bill No", "Date", "Status", "Amount"], table_rows, amount_cols={3})
    html = stat_row([("Total Bills", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_sale_receipts(rows, proj_map):
    html = section_header("Sale Receipts")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = [[r.receipt_no or "—", str(r.receipt_date) if r.receipt_date else "—", r.workflow_status] for r in items]
        html += table(["Receipt No", "Date", "Status"], table_rows)
    return html


def _render_purchase_vouchers(rows, proj_map):
    html = section_header("Purchase Vouchers")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([r.voucher_no, r.workflow_status, r.total_invoice_amount])
            total_count += 1
            total_amt += float(r.total_invoice_amount or 0)
        html += table(["Voucher No", "Status", "Amount"], table_rows, amount_cols={2})
    html = stat_row([("Total Vouchers", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_payment_vouchers(rows, proj_map):
    html = section_header("Payment Vouchers")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([r.payment_voucher_no, r.workflow_status, r.total_invoice_amount])
            total_count += 1
            total_amt += float(r.total_invoice_amount or 0)
        html += table(["Voucher No", "Status", "Amount"], table_rows, amount_cols={2})
    html = stat_row([("Total Vouchers", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_journal_entries(rows, proj_map):
    html = section_header("Journal Entries")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = [[r.entry_no or "—", str(r.entry_date) if r.entry_date else "—", r.workflow_status] for r in items]
        html += table(["Entry No", "Date", "Status"], table_rows)
    return html


def _render_simple_project(rows, proj_map, heading, no_col, date_col_name, date_attr):
    html = section_header(heading)
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = [
            [getattr(r, no_col) or "—", str(getattr(r, date_attr)) if getattr(r, date_attr) else "—", r.workflow_status]
            for r in items
        ]
        html += table([heading.rstrip("s") + " No", date_col_name, "Status"], table_rows)
    return html


def _render_petty_cash(rows, proj_map):
    html = section_header("Petty Cash Docket Vouchers")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([r.voucher_no or "—", r.workflow_status, r.total_amount])
            total_count += 1
            total_amt += float(r.total_amount or 0)
        html += table(["Voucher No", "Status", "Amount"], table_rows, amount_cols={2})
    html = stat_row([("Total Vouchers", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_bill_payments(rows, proj_map):
    html = section_header("Bill Payments")
    if not rows:
        return html + no_data_note()
    groups = _group_by_project(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        table_rows = []
        for r in items:
            table_rows.append([r.receipt_no or "—", r.workflow_status, r.total_invoice_amount])
            total_count += 1
            total_amt += float(r.total_invoice_amount or 0)
        html += table(["Receipt No", "Status", "Amount"], table_rows, amount_cols={2})
    html = stat_row([("Total Payments", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


# ── main summary builder ──────────────────────────────────────────────────────

def build_and_send():
    start, end = last_month_range()
    proj_map   = _project_map()

    pb   = _query(PurchaseBillMaster,        start, end)
    sb   = _query(SaleBillMaster,            start, end)
    sr   = _query(SaleReceiptMaster,         start, end)
    pv   = _query(PurchaseVoucherMaster,     start, end)
    pmv  = _query(PaymentVoucherMaster,      start, end)
    je   = _query(JournalEntryMaster,        start, end)
    ce   = _query(ContraEntryMaster,         start, end)
    cn   = _query(CreditNoteMaster,          start, end)
    dn   = _query(DebitNoteMaster,           start, end)
    pc   = _query(PettyCashDocketVoucher,    start, end)
    bp   = _query(BillPaymentReceiptMaster,  start, end)

    # overall stats
    overview = stat_row([
        ("Purchase Bills",    str(len(pb))),
        ("Sale Bills",        str(len(sb))),
        ("Payment Vouchers",  str(len(pmv))),
        ("Petty Cash",        str(len(pc))),
    ])

    body = (
        overview
        + _render_purchase_bills(pb,  proj_map)
        + _render_sale_bills(sb,      proj_map)
        + _render_sale_receipts(sr,   proj_map)
        + _render_purchase_vouchers(pv,  proj_map)
        + _render_payment_vouchers(pmv,  proj_map)
        + _render_journal_entries(je,    proj_map)
        + _render_simple_project(ce,  proj_map, "Contra Entries",    "contra_no", "Date", "entry_date")
        + _render_simple_project(cn,  proj_map, "Credit Notes",      "credit_note_no", "Date", "note_date")
        + _render_simple_project(dn,  proj_map, "Debit Notes",       "debit_note_no", "Date", "note_date")
        + _render_petty_cash(pc,  proj_map)
        + _render_bill_payments(bp,   proj_map)
    )

    pl    = period_label(start, end)
    html  = build_email("Finance Module", pl, datetime.now(), body)
    subject = f"[ERP] Finance Module — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_FINANCE", ""),
    )
