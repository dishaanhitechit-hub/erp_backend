"""
Bulk Expenses Docket (Petty Cash Docket Voucher) import — Excel / CSV.

Same shape as the Journal bulk upload: the frontend parses the file into plain
rows and posts them here. One row = one CC expense line; rows sharing the same
``docketRef`` become one docket (DV…, Draft).

Every docket must reference an Approved petty-cash budget of the project.
A CC line may use any valid CC code — same as the single docket form, CCs that
are not in the budget are allowed (saved without a budget line link). For CCs
that ARE in the budget the amount may not exceed what is left of that CC's
budget (other dockets incl. earlier dockets of the same file count).

Endpoints (see routes.py):
  GET  /finance/petty-cash/docket-voucher/bulk/reference?projectCode
       → approved budgets (with per-CC balance) + project cash/bank accounts,
         used for the template's reference sheets
  POST /finance/petty-cash/docket-voucher/bulk/validate  → dry run
  POST /finance/petty-cash/docket-voucher/bulk/import    → creates valid dockets
       as Draft, returns invalid ones with errors to fix and re-send

Row payload (all values may be raw strings from the sheet):
  { rowNo, docketRef, date, budgetNo, expensesBy, paymentMode, accountCode,
    transactionId, ccCode, description, amount }
"""

import re
import uuid as _uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.response import res
from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher, PettyCashDocketVoucherDetail
from app.models.pettyCashBudget import PettyCashBudget
from app.models.bankCash import BankCash, BankCashProject
from app.models.cc_code import CCCode
from app.models.project import Project
from app.modules.work_flow import is_creator

_MODULE = "petty_cash"
MAX_ROWS = 5000
MAX_DOCKETS = 1000
_TWO = Decimal("0.01")
_EXCLUDED_STATUSES = ("Rejected",)   # same rule as get_budget_rows_for_voucher

# header fields: payload key → label used in messages
_HEADER_FIELDS = {
    "date":          "Date",
    "budgetNo":      "Budget No",
    "expensesBy":    "Expenses By",
    "paymentMode":   "Payment Mode",
    "accountCode":   "Account Code",
    "transactionId": "Transaction ID",
}

_MODE_ALIASES = {
    "cash": "Cash", "petty": "Cash", "pettycash": "Cash",
    "bank": "Bank/UPI", "upi": "Bank/UPI", "bankupi": "Bank/UPI", "online": "Bank/UPI",
    "neft": "Bank/UPI", "rtgs": "Bank/UPI", "imps": "Bank/UPI", "cheque": "Bank/UPI",
    "check": "Bank/UPI", "card": "Bank/UPI", "banktransfer": "Bank/UPI",
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y",
)


# ── normalisers ──────────────────────────────────────────────────

def _s(v):
    return "" if v is None else str(v).strip()


def _key(v):
    return re.sub(r"[\s_\-./]", "", _s(v).lower())


def _parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raw = _s(v)
    if not raw:
        return None
    raw = raw.split("T")[0].split(" 00:00")[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(raw, fmt).date()
            if 1900 <= d.year <= 9999:
                return d
        except ValueError:
            continue
    return None


def _parse_amount(v):
    """Returns (Decimal|None, error|None). Blank → None (required)."""
    raw = _s(v).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    if raw in ("", "-"):
        return None, "Amount is required"
    try:
        amt = Decimal(raw)
    except InvalidOperation:
        return None, f"Amount '{_s(v)}' is not a valid number"
    if amt <= 0:
        return None, "Amount must be greater than 0"
    return amt.quantize(_TWO, rounding=ROUND_HALF_UP), None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if d else None


def _money(d):
    return f"{d:,.2f}"


# ── lookups (loaded once per request) ────────────────────────────

def _used_map(budget_ids):
    """(budget_id, CC_CODE) → Decimal used by existing non-rejected dockets."""
    if not budget_ids:
        return {}
    q = (
        db.session.query(
            PettyCashDocketVoucher.budget_id,
            PettyCashDocketVoucherDetail.cc_code,
            func.coalesce(func.sum(PettyCashDocketVoucherDetail.amount), 0),
        )
        .join(PettyCashDocketVoucher, PettyCashDocketVoucher.id == PettyCashDocketVoucherDetail.voucher_id)
        .filter(
            PettyCashDocketVoucher.budget_id.in_(budget_ids),
            PettyCashDocketVoucher.workflow_status.notin_(_EXCLUDED_STATUSES),
        )
        .group_by(PettyCashDocketVoucher.budget_id, PettyCashDocketVoucherDetail.cc_code)
        .all()
    )
    return {(bid, (cc or "").upper()): Decimal(str(amt or 0)) for bid, cc, amt in q}


def _project_accounts(project):
    return (
        BankCash.query
        .join(BankCashProject, BankCashProject.bank_cash_id == BankCash.id)
        .filter(BankCashProject.project_id == project.id)
        .order_by(BankCash.bank_code)
        .all()
    )


class _Lookups:
    def __init__(self, project, budget_nos, cc_codes):
        # approved + rejected/other budgets of this project, keyed by budget_no
        self.budget = {}
        if budget_nos:
            for b in PettyCashBudget.query.filter(
                PettyCashBudget.project_code == project.project_code,
                func.upper(PettyCashBudget.budget_no).in_(budget_nos),
            ).all():
                self.budget[b.budget_no.upper()] = b
        # budget lines: (budget_id, CC_CODE) → detail
        self.budget_line = {}
        for b in self.budget.values():
            for d in b.details:
                self.budget_line.setdefault((b.id, (d.cc_code or "").upper()), d)
        approved_ids = [b.id for b in self.budget.values() if b.workflow_status == "Approved"]
        self.used = _used_map(approved_ids)

        self.cc = {}
        if cc_codes:
            for c in CCCode.query.filter(func.upper(CCCode.cc_code).in_(cc_codes)).all():
                self.cc[c.cc_code.upper()] = c

        # cash / bank accounts linked to the project
        self.accounts = {}
        self.by_type = {"CASH": [], "BANK": []}
        for a in _project_accounts(project):
            self.accounts[(a.bank_code or "").upper()] = a
            t = (a.type or "").upper()
            if t in self.by_type:
                self.by_type[t].append(a)
        self._acc_all = None

    def find_account(self, code, mode):
        """Returns (BankCash|None, error|None)."""
        want = "CASH" if mode == "Cash" else "BANK"
        if not code:
            opts = self.by_type.get(want, [])
            if len(opts) == 1:
                return opts[0], None
            if not opts:
                return None, f"No {want.title()} account is linked to this project"
            return None, f"Account Code is required — project has {len(opts)} {want.title()} accounts"
        acc = self.accounts.get(code.upper())
        if not acc:
            if self._acc_all is None:
                self._acc_all = {
                    (a.bank_code or "").upper()
                    for a in BankCash.query.filter(func.upper(BankCash.bank_code) == code.upper()).all()
                }
            if code.upper() in self._acc_all:
                return None, f"Account '{code}' is not linked to this project"
            return None, f"Account '{code}' not found"
        if (acc.type or "").upper() != want:
            return None, f"Account '{code}' is a {(acc.type or '').title()} account but Payment Mode is {mode}"
        return acc, None


# ── core validation ──────────────────────────────────────────────

def _validate(rows, project):
    norm = []
    budget_nos, cc_codes = set(), set()
    for i, r in enumerate(rows, start=1):
        n = {
            "rowNo":         r.get("rowNo") or i,
            "docketRef":     _s(r.get("docketRef")),
            "date":          _s(r.get("date")),
            "budgetNo":      _s(r.get("budgetNo")),
            "expensesBy":    _s(r.get("expensesBy")),
            "paymentMode":   _s(r.get("paymentMode")),
            "accountCode":   _s(r.get("accountCode")),
            "transactionId": _s(r.get("transactionId")),
            "ccCode":        _s(r.get("ccCode")),
            "description":   _s(r.get("description")),
            "amount":        _s(r.get("amount")),
        }
        if n["budgetNo"]:
            budget_nos.add(n["budgetNo"].upper())
        if n["ccCode"]:
            cc_codes.add(n["ccCode"].upper())
        norm.append(n)

    lk = _Lookups(project, budget_nos, cc_codes)

    groups, order = {}, []
    for n in norm:
        ref = n["docketRef"] or f"__row{n['rowNo']}"
        if ref not in groups:
            groups[ref] = []
            order.append(ref)
        groups[ref].append(n)

    # running budget usage across dockets of this upload: (budget_id, CC) → Decimal
    running = {}

    dockets = []
    for ref in order:
        g_rows = groups[ref]
        d_errors = []
        if ref.startswith("__row"):
            d_errors.append("Docket Ref is missing")

        # ── header fields: must be identical on every row (blanks inherit) ──
        hdr = {}
        for f, label in _HEADER_FIELDS.items():
            vals = []
            for n in g_rows:
                v = n[f]
                if v and v.lower() not in [x.lower() for x in vals]:
                    vals.append(v)
            if len(vals) > 1:
                d_errors.append(f"All rows of a docket must have the same {label} (found {', '.join(vals[:3])})")
            hdr[f] = vals[0] if vals else ""

        hdr_err_fields = set()

        v_date = _parse_date(hdr["date"])
        if not hdr["date"]:
            d_errors.append("Date is required"); hdr_err_fields.add("date")
        elif not v_date:
            d_errors.append(f"Invalid date '{hdr['date']}' (use DD-MM-YYYY)"); hdr_err_fields.add("date")

        if not hdr["expensesBy"]:
            d_errors.append("Expenses By is required"); hdr_err_fields.add("expensesBy")
        elif len(hdr["expensesBy"]) > 100:
            d_errors.append("Expenses By is longer than 100 characters"); hdr_err_fields.add("expensesBy")

        mode = _MODE_ALIASES.get(_key(hdr["paymentMode"])) if hdr["paymentMode"] else None
        if not hdr["paymentMode"]:
            d_errors.append("Payment Mode is required (Cash or Bank/UPI)"); hdr_err_fields.add("paymentMode")
        elif not mode:
            d_errors.append(f"Payment Mode must be Cash or Bank/UPI (got '{hdr['paymentMode']}')"); hdr_err_fields.add("paymentMode")

        account = None
        if mode:
            account, err = lk.find_account(hdr["accountCode"], mode)
            if err:
                d_errors.append(err); hdr_err_fields.add("accountCode")

        if len(hdr["transactionId"]) > 100:
            d_errors.append("Transaction ID is longer than 100 characters"); hdr_err_fields.add("transactionId")

        budget = None
        if not hdr["budgetNo"]:
            d_errors.append("Budget No is required — every docket must reference an approved budget"); hdr_err_fields.add("budgetNo")
        else:
            budget = lk.budget.get(hdr["budgetNo"].upper())
            if not budget:
                d_errors.append(f"Budget '{hdr['budgetNo']}' not found in this project"); hdr_err_fields.add("budgetNo")
            elif budget.workflow_status != "Approved":
                d_errors.append(f"Budget '{budget.budget_no}' is {budget.workflow_status} — only Approved budgets can be used"); hdr_err_fields.add("budgetNo")
                budget = None

        if mode == "Cash" and len(g_rows) > 1:
            d_errors.append("A Cash docket can have only 1 line — use separate Docket Refs")

        # ── lines ──
        out_rows = []
        line_amt = {}          # CC → Decimal (this docket)
        total = Decimal("0")
        for n in g_rows:
            errs = []
            cc_obj = None
            line = None
            cc = n["ccCode"]
            if not cc:
                errs.append("CC Code is required")
            else:
                cc_obj = lk.cc.get(cc.upper())
                if not cc_obj:
                    errs.append(f"CC code '{cc}' not found")
                elif budget is not None:
                    # not-in-budget CCs are allowed (no budget line → no balance check)
                    line = lk.budget_line.get((budget.id, cc.upper()))

            amt, e = _parse_amount(n["amount"])
            if e:
                errs.append(e)
            if len(n["description"]) > 255:
                errs.append("Description is longer than 255 characters")

            if not errs:
                total += amt
                line_amt[cc.upper()] = line_amt.get(cc.upper(), Decimal("0")) + amt

            out_rows.append({
                "rowNo":          n["rowNo"],
                "docketRef":      n["docketRef"],
                "date":           n["date"],
                "budgetNo":       n["budgetNo"],
                "expensesBy":     n["expensesBy"],
                "paymentMode":    n["paymentMode"],
                "accountCode":    n["accountCode"],
                "transactionId":  n["transactionId"],
                "ccCode":         cc_obj.cc_code if cc_obj else cc,
                "ccName":         cc_obj.cc_name if cc_obj else None,
                "budgetDetailId": line.id if line else None,
                "inBudget":       bool(line),
                "description":    n["description"],
                "amount":         n["amount"] if errs else float(amt),
                "errors":         errs,
            })

        # ── budget balance (per CC, cumulative over the upload) ──
        row_errors = any(r["errors"] for r in out_rows)
        balance_info = []
        if budget is not None and not row_errors:
            over = False
            for cc_u, amt in line_amt.items():
                bl = lk.budget_line.get((budget.id, cc_u))
                if not bl:
                    continue
                allotted = Decimal(str(bl.budget_amount or 0))
                used = lk.used.get((budget.id, cc_u), Decimal("0")) + running.get((budget.id, cc_u), Decimal("0"))
                remaining = allotted - used
                balance_info.append({
                    "ccCode": bl.cc_code, "budget": float(allotted),
                    "used": float(used), "remaining": float(remaining), "thisDocket": float(amt),
                })
                if amt > remaining:
                    over = True
                    msg = (f"Exceeds budget for {bl.cc_code}: balance {_money(max(remaining, Decimal('0')))}, "
                           f"this docket {_money(amt)}")
                    for r in out_rows:
                        if (r["ccCode"] or "").upper() == cc_u:
                            r["errors"].append(msg)
            row_errors = row_errors or over

        if len(g_rows) > 200:
            d_errors.append("A docket can have at most 200 lines")

        valid = not row_errors and not d_errors
        if valid and budget is not None:
            for cc_u, amt in line_amt.items():
                running[(budget.id, cc_u)] = running.get((budget.id, cc_u), Decimal("0")) + amt

        dockets.append({
            "docketRef":     "" if ref.startswith("__row") else ref,
            "date":          _fmt(v_date),
            "budgetId":      budget.id if budget else None,
            "budgetNo":      budget.budget_no if budget else hdr["budgetNo"],
            "expensesBy":    hdr["expensesBy"],
            "paymentMode":   mode or hdr["paymentMode"],
            "bankCashId":    account.id if account else None,
            "accountCode":   account.bank_code if account else hdr["accountCode"],
            "accountName":   (account.bank_holder_name or account.bank_name) if account else None,
            "transactionId": hdr["transactionId"],
            "totalAmount":   float(total),
            "lineCount":     len(g_rows),
            "valid":         valid,
            "errors":        d_errors,
            "errorFields":   sorted(hdr_err_fields),
            "budgetBalance": balance_info,
            "rows":          out_rows,
        })

    return dockets


def _summary(dockets):
    valid = [d for d in dockets if d["valid"]]
    return {
        "totalDockets":   len(dockets),
        "validDockets":   len(valid),
        "invalidDockets": len(dockets) - len(valid),
        "totalRows":      sum(d["lineCount"] for d in dockets),
        "validAmount":    round(sum(d["totalAmount"] for d in valid), 2),
    }


def _precheck(data, user_id, need_rows=True):
    project_code = data.get("projectCode")
    if not project_code:
        return None, None, res("projectCode required", [], 400)
    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, None, res("Project not found", [], 404)
    if not is_creator(project_code, _MODULE, user_id):
        return None, None, res("You are not authorized to create docket vouchers", [], 403)
    if not need_rows:
        return project, None, None
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return None, None, res("No rows found in the file", [], 400)
    if len(rows) > MAX_ROWS:
        return None, None, res(f"Too many rows ({len(rows)}). Max {MAX_ROWS} per upload — split the file.", [], 400)
    return project, rows, None


# ══════════════════════════════════════════════════════════════════
# PUBLIC: REFERENCE DATA (template sheets)
# ══════════════════════════════════════════════════════════════════

def get_bulk_docket_reference(data, user_id):
    try:
        project, _, err = _precheck(data, user_id, need_rows=False)
        if err:
            return err
        budgets = (
            PettyCashBudget.query
            .filter_by(project_code=project.project_code, workflow_status="Approved")
            .order_by(PettyCashBudget.id.desc())
            .all()
        )
        used = _used_map([b.id for b in budgets])
        out_b = []
        for b in budgets:
            rows = []
            for d in b.details:
                allotted = Decimal(str(d.budget_amount or 0))
                u = used.get((b.id, (d.cc_code or "").upper()), Decimal("0"))
                rows.append({
                    "ccCode": d.cc_code, "ccName": d.cc_name,
                    "shortDescription": d.short_description,
                    "budgetAmount": float(allotted), "usedAmount": float(u),
                    "remaining": float(allotted - u),
                })
            out_b.append({
                "id": b.id, "budgetNo": b.budget_no,
                "fromDate": _fmt(b.from_date), "toDate": _fmt(b.to_date),
                "totalBudget": float(b.total_budget_amount or 0),
                "rows": rows,
            })
        accounts = [{
            "id": a.id, "bankCode": a.bank_code, "type": (a.type or "").upper(),
            "name": a.bank_holder_name or a.bank_name or "",
        } for a in _project_accounts(project)]
        return res("Reference data fetched", {"budgets": out_b, "accounts": accounts}, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# PUBLIC: VALIDATE (dry run)
# ══════════════════════════════════════════════════════════════════

def validate_bulk_docket(data, user_id):
    try:
        project, rows, err = _precheck(data, user_id)
        if err:
            return err
        dockets = _validate(rows, project)
        if len(dockets) > MAX_DOCKETS:
            return res(f"Too many dockets ({len(dockets)}). Max {MAX_DOCKETS} per upload.", [], 400)
        return res("Validated", {"summary": _summary(dockets), "dockets": dockets}, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# PUBLIC: IMPORT (creates valid dockets as Draft)
# ══════════════════════════════════════════════════════════════════

def import_bulk_docket(data, user_id):
    try:
        project, rows, err = _precheck(data, user_id)
        if err:
            return err
        dockets = _validate(rows, project)
        if len(dockets) > MAX_DOCKETS:
            return res(f"Too many dockets ({len(dockets)}). Max {MAX_DOCKETS} per upload.", [], 400)

        from app.modules.finance.petty_cash.docket_voucher.service import _generate_voucher_no

        created, failed = [], []
        for d in dockets:
            if not d["valid"]:
                failed.append(d)
                continue
            try:
                voucher = PettyCashDocketVoucher(
                    voucher_uuid    = str(_uuid.uuid4()),
                    voucher_no      = _generate_voucher_no(),
                    voucher_date    = datetime.strptime(d["date"], "%Y-%m-%d").date(),
                    budget_id       = d["budgetId"],
                    expenses_by     = d["expensesBy"],
                    mode_of_payment = d["paymentMode"],
                    bank_cash_id    = d["bankCashId"],
                    payment_ref_id  = d["transactionId"] or None,
                    project_code    = project.project_code,
                    total_amount    = Decimal(str(d["totalAmount"])),
                    workflow_status = "Draft",
                    current_level   = 0,
                    locked          = False,
                    created_by      = user_id,
                )
                db.session.add(voucher)
                db.session.flush()
                for sl, r in enumerate(d["rows"], start=1):
                    db.session.add(PettyCashDocketVoucherDetail(
                        voucher_id        = voucher.id,
                        sl_no             = sl,
                        budget_detail_id  = r["budgetDetailId"],
                        cc_code           = r["ccCode"],
                        cc_name           = r["ccName"],
                        short_description = r["description"] or None,
                        amount            = Decimal(str(r["amount"] or 0)),
                    ))
                db.session.commit()
                created.append({
                    "docketRef": d["docketRef"],
                    "id":        voucher.id,
                    "voucherNo": voucher.voucher_no,
                    "date":      d["date"],
                    "budgetNo":  d["budgetNo"],
                    "expensesBy": d["expensesBy"],
                    "amount":    d["totalAmount"],
                    "lineCount": d["lineCount"],
                })
            except Exception as e:
                db.session.rollback()
                d["valid"] = False
                d["errors"] = d["errors"] + [f"Could not save: {e}"]
                failed.append(d)

        msg = f"{len(created)} expense docket{'' if len(created) == 1 else 's'} created as Draft"
        if failed:
            msg += f", {len(failed)} need correction"
        return res(msg, {
            "created": created,
            "failed":  failed,
            "summary": {
                "createdCount":  len(created),
                "failedCount":   len(failed),
                "createdAmount": round(sum(c["amount"] for c in created), 2),
            },
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
