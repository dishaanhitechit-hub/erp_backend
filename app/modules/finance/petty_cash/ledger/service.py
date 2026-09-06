import math
from sqlalchemy import func
from app.extensions import db
from datetime import datetime

from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher
from app.models.contraEntry import ContraEntryMaster, ContraEntryLine
from app.models.bankCash import BankCash, BankCashProject
from app.models.project import Project
from app.response import res


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _account_payload(bc):
    return {
        "bankCashId":  bc.id,
        "bankCode":    bc.bank_code,
        "bankName":    bc.bank_holder_name or bc.bank_name,
        "accountType": bc.type,
    }


def _get_project_account_ids(project_code):
    """Return list of bank_cash_id values linked to the project."""
    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return []
    rows = BankCashProject.query.filter_by(project_id=project.id).all()
    return [r.bank_cash_id for r in rows]


# ══════════════════════════════════════════════════════════════════
# 1. PROJECT LINKED ACCOUNTS
# ══════════════════════════════════════════════════════════════════

def get_project_linked_accounts(params):
    try:
        project_code = params.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return res("Project not found", [], 404)

        rows = (
            BankCashProject.query
            .filter_by(project_id=project.id)
            .join(BankCash, BankCash.id == BankCashProject.bank_cash_id)
            .all()
        )

        accounts = [_account_payload(r.bank_cash) for r in rows if r.bank_cash]
        return res("Project accounts fetched", {"accounts": accounts}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. ACCOUNT LEDGER
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_account_ledger(params):
    try:
        project_code = params.get("projectCode")
        bank_cash_id = params.get("bankCashId")
        page         = max(1, int(params.get("page", 1) or 1))
        page_size    = max(1, int(params.get("pageSize", 10) or 10))
        from_date    = params.get("fromDate")
        to_date      = params.get("toDate")

        if not project_code:
            return res("projectCode required", [], 400)

        # Resolve which account(s) to show
        if bank_cash_id:
            account_ids = [int(bank_cash_id)]
            bc = BankCash.query.get(int(bank_cash_id))
            if not bc:
                return res("Account not found", [], 404)
            account_info = _account_payload(bc)
        else:
            account_ids = _get_project_account_ids(project_code)
            if not account_ids:
                return res("No accounts linked to this project", [], 404)
            account_info = None  # multiple accounts

        # ── CR entries: contra lines where this account is credited ──
        contra_q = (
            db.session.query(ContraEntryLine, ContraEntryMaster)
            .join(ContraEntryMaster, ContraEntryMaster.id == ContraEntryLine.contra_id)
            .filter(
                ContraEntryMaster.project_code == project_code,
                ContraEntryMaster.workflow_status == "Approved",
                ContraEntryLine.account_id.in_(account_ids),
                ContraEntryLine.dr_cr == "Cr",
            )
        )
        if from_date:
            contra_q = contra_q.filter(ContraEntryMaster.entry_date >= from_date)
        if to_date:
            contra_q = contra_q.filter(ContraEntryMaster.entry_date <= to_date)

        cr_entries = []
        for line, master in contra_q.all():
            bc = BankCash.query.get(line.account_id)
            cr_entries.append({
                "date":        master.entry_date,
                "type":        "Contra",
                "referenceNo": master.voucher_no,
                "description": master.remarks or "Contra entry",
                "bankCode":    bc.bank_code if bc else None,
                "accountType": bc.type if bc else None,
                "debit":       0.0,
                "credit":      float(line.credit_amount or 0),
            })

        # ── DR entries: approved docket vouchers ─────────────────────
        docket_q = PettyCashDocketVoucher.query.filter(
            PettyCashDocketVoucher.project_code == project_code,
            PettyCashDocketVoucher.workflow_status == "Approved",
            PettyCashDocketVoucher.bank_cash_id.in_(account_ids),
        )
        if from_date:
            docket_q = docket_q.filter(PettyCashDocketVoucher.voucher_date >= from_date)
        if to_date:
            docket_q = docket_q.filter(PettyCashDocketVoucher.voucher_date <= to_date)

        dr_entries = []
        for v in docket_q.all():
            bc = v.bank_cash
            dr_entries.append({
                "date":        v.voucher_date,
                "type":        "Docket",
                "referenceNo": v.voucher_no,
                "description": v.expenses_by,
                "bankCode":    bc.bank_code if bc else None,
                "accountType": bc.type if bc else None,
                "debit":       float(v.total_amount or 0),
                "credit":      0.0,
            })

        # ── Merge & sort by date ──────────────────────────────────────
        all_entries = sorted(cr_entries + dr_entries, key=lambda x: x["date"])

        # ── Running balance ───────────────────────────────────────────
        balance = 0.0
        for entry in all_entries:
            balance += entry["credit"] - entry["debit"]
            entry["balance"] = round(balance, 2)
            entry["date"]    = _fmt(entry["date"])

        # ── Summary ───────────────────────────────────────────────────
        total_credit = sum(e["credit"] for e in all_entries)
        total_debit  = sum(e["debit"]  for e in all_entries)

        # ── Pending dockets (not affecting balance) ───────────────────
        _PENDING_EXCLUDE = ("Approved", "Rejected")
        pending_vouchers = PettyCashDocketVoucher.query.filter(
            PettyCashDocketVoucher.project_code == project_code,
            PettyCashDocketVoucher.bank_cash_id.in_(account_ids),
            PettyCashDocketVoucher.workflow_status.notin_(_PENDING_EXCLUDE),
        ).order_by(PettyCashDocketVoucher.voucher_date.asc()).all()

        pending_entries = []
        for v in pending_vouchers:
            bc = v.bank_cash
            pending_entries.append({
                "date":           _fmt(v.voucher_date),
                "type":           "Docket",
                "referenceNo":    v.voucher_no,
                "description":    v.expenses_by,
                "bankCode":       bc.bank_code if bc else None,
                "accountType":    bc.type if bc else None,
                "debit":          float(v.total_amount or 0),
                "credit":         0.0,
                "workflowStatus": v.workflow_status,
            })

        pending_debit = sum(e["debit"] for e in pending_entries)

        summary = {
            "totalCredit":  round(total_credit, 2),
            "totalDebit":   round(total_debit, 2),
            "balance":      round(total_credit - total_debit, 2),
            "pendingDebit": round(pending_debit, 2),
        }

        # ── Pagination ────────────────────────────────────────────────
        total        = len(all_entries)
        start        = (page - 1) * page_size
        page_entries = all_entries[start: start + page_size]

        return res("Petty cash account ledger fetched", {
            "account":        account_info,
            "entries":        page_entries,
            "pendingEntries": pending_entries,
            "summary":        summary,
            "pagination": {
                "page":       page,
                "pageSize":   page_size,
                "total":      total,
                "totalPages": math.ceil(total / page_size) if page_size else 1,
            },
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)
