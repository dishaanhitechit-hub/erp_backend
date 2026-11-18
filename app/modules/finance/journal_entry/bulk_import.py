"""
Bulk Journal Entry import (Excel / CSV).

The frontend parses the uploaded file (xlsx / xls / csv) into plain rows and
posts them here. One row = one Dr or Cr line; rows sharing the same
``voucherRef`` become one journal entry (JV, Draft).

Endpoints (see routes.py):
  POST /finance/journal-entry/bulk/validate  → dry run, no DB writes
  POST /finance/journal-entry/bulk/import    → creates every valid voucher,
                                               returns the invalid ones with
                                               errors so the user can fix and
                                               re-send only those.

Row payload (all values may be raw strings from the sheet):
  { rowNo, voucherRef, date, drCr, accountType, accountCode,
    debit, credit, remarks }
"""

import re
import uuid as _uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.response import res
from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.cc_code import CCCode
from app.models.vendor import Vendor
from app.models.project import Project
from app.modules.work_flow import is_creator

_MODULE = "journal"
MAX_ROWS = 5000
MAX_VOUCHERS = 1000
_TWO = Decimal("0.01")

# ── normalisers ──────────────────────────────────────────────────

_TYPE_ALIASES = {
    "cc": "CC", "cccode": "CC", "costcentre": "CC", "costcenter": "CC", "expense": "CC",
    "vendor": "Vendor", "ledger": "Vendor", "party": "Vendor", "supplier": "Vendor",
    "creditor": "Vendor", "debtor": "Vendor", "subcontractor": "Vendor",
    "customer": "Customer", "client": "Customer",
}

_DRCR_ALIASES = {"dr": "Dr", "debit": "Dr", "d": "Dr", "cr": "Cr", "credit": "Cr", "c": "Cr"}

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y",
)


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
    """Returns (Decimal|None, error|None). Blank → 0."""
    raw = _s(v).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    if raw in ("", "-"):
        return Decimal("0"), None
    try:
        amt = Decimal(raw)
    except InvalidOperation:
        return None, f"'{_s(v)}' is not a valid amount"
    if amt < 0:
        return None, "Amount cannot be negative"
    return amt.quantize(_TWO, rounding=ROUND_HALF_UP), None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if d else None


# ── lookups (loaded once per request) ────────────────────────────

class _Lookups:
    def __init__(self, codes_cc, codes_vendor):
        self.cc = {}
        if codes_cc:
            for c in CCCode.query.filter(func.upper(CCCode.cc_code).in_(codes_cc)).all():
                self.cc[c.cc_code.upper()] = c
        self.vendor = {}
        self.vendor_by_name = {}
        if codes_vendor:
            for v in Vendor.query.filter(func.upper(Vendor.ledger_code).in_(codes_vendor)).all():
                if v.ledger_code:
                    self.vendor[v.ledger_code.upper()] = v
            # fall back: allow the ledger *name* in the code column
            for v in Vendor.query.filter(func.upper(Vendor.ledger_name).in_(codes_vendor)).all():
                if v.ledger_name:
                    self.vendor_by_name.setdefault(v.ledger_name.upper(), []).append(v)

    def find(self, acc_type, code):
        """Returns (resolved_type, obj, error)."""
        u = code.upper()
        if acc_type == "CC":
            obj = self.cc.get(u)
            return ("CC", obj, None) if obj else ("CC", None, f"CC code '{code}' not found")
        if acc_type == "Vendor":
            obj = self.vendor.get(u)
            if obj:
                return "Vendor", obj, None
            by_name = self.vendor_by_name.get(u) or []
            if len(by_name) == 1:
                return "Vendor", by_name[0], None
            if len(by_name) > 1:
                return "Vendor", None, f"Ledger name '{code}' matches {len(by_name)} ledgers — use the ledger code"
            return "Vendor", None, f"Ledger code '{code}' not found"
        # type blank → infer
        if u in self.cc and u not in self.vendor:
            return "CC", self.cc[u], None
        if u in self.vendor and u not in self.cc:
            return "Vendor", self.vendor[u], None
        if u in self.cc and u in self.vendor:
            return None, None, f"'{code}' exists as both CC and Ledger — set Account Type"
        return None, None, f"Account '{code}' not found as CC code or Ledger code"


# ── core validation ──────────────────────────────────────────────

def _validate(rows, client_name):
    """Group rows into vouchers and validate. Pure function except lookups."""
    # pre-normalise
    norm = []
    cc_codes, vendor_codes = set(), set()
    for i, r in enumerate(rows, start=1):
        acc_type_raw = _s(r.get("accountType"))
        acc_type = _TYPE_ALIASES.get(_key(acc_type_raw)) if acc_type_raw else None
        code = _s(r.get("accountCode"))
        n = {
            "rowNo":       r.get("rowNo") or i,
            "voucherRef":  _s(r.get("voucherRef")),
            "date":        _s(r.get("date")),
            "drCr":        _s(r.get("drCr")),
            "accountType": acc_type_raw,
            "accountCode": code,
            "debit":       _s(r.get("debit")),
            "credit":      _s(r.get("credit")),
            "remarks":     _s(r.get("remarks")),
            "_type":       acc_type,
            "_typeBad":    bool(acc_type_raw) and acc_type is None,
        }
        if code:
            if acc_type in ("CC", None):
                cc_codes.add(code.upper())
            if acc_type in ("Vendor", None):
                vendor_codes.add(code.upper())
        norm.append(n)

    lk = _Lookups(cc_codes, vendor_codes)

    groups = {}
    order = []
    for n in norm:
        ref = n["voucherRef"] or f"__row{n['rowNo']}"
        if ref not in groups:
            groups[ref] = []
            order.append(ref)
        groups[ref].append(n)

    vouchers = []
    for ref in order:
        g_rows = groups[ref]
        v_errors = []
        dates = set()
        remarks = ""
        tot_dr = Decimal("0")
        tot_cr = Decimal("0")
        out_rows = []
        n_dr = n_cr = 0

        if ref.startswith("__row"):
            v_errors.append("Voucher Ref is missing")

        for n in g_rows:
            errs = []
            # date
            d = _parse_date(n["date"])
            if not n["date"]:
                errs.append("Date is required")
            elif not d:
                errs.append(f"Invalid date '{n['date']}' (use DD-MM-YYYY)")
            else:
                dates.add(d)

            # amounts
            dr_amt, e1 = _parse_amount(n["debit"])
            cr_amt, e2 = _parse_amount(n["credit"])
            if e1: errs.append(f"Debit: {e1}")
            if e2: errs.append(f"Credit: {e2}")
            dr_amt = dr_amt or Decimal("0")
            cr_amt = cr_amt or Decimal("0")

            # Dr / Cr side
            side_raw = n["drCr"]
            side = _DRCR_ALIASES.get(_key(side_raw)) if side_raw else None
            if side_raw and not side:
                errs.append(f"Dr/Cr must be 'Dr' or 'Cr' (got '{side_raw}')")
            if not side and not side_raw:
                if dr_amt > 0 and cr_amt == 0:
                    side = "Dr"
                elif cr_amt > 0 and dr_amt == 0:
                    side = "Cr"
            if dr_amt > 0 and cr_amt > 0:
                errs.append("Fill either Debit or Credit, not both")
            elif side == "Dr":
                if dr_amt <= 0 and not e1:
                    # tolerate amount placed in the Credit column for a Dr row
                    if cr_amt > 0:
                        errs.append("Dr row has amount in Credit column")
                    else:
                        errs.append("Debit amount must be greater than 0")
            elif side == "Cr":
                if cr_amt <= 0 and not e2:
                    if dr_amt > 0:
                        errs.append("Cr row has amount in Debit column")
                    else:
                        errs.append("Credit amount must be greater than 0")
            elif not side_raw and not (e1 or e2):
                errs.append("Dr/Cr is required (or enter an amount in Debit or Credit)")

            # account
            acc_type = n["_type"]
            account_id = None
            account_name = None
            resolved_type = acc_type
            if n["_typeBad"]:
                errs.append(f"Account Type must be CC, Vendor or Customer (got '{n['accountType']}')")
            elif acc_type == "Customer":
                account_name = client_name or n["accountCode"] or None
                if not account_name:
                    errs.append("Project has no client name set — cannot use Customer")
            elif not n["accountCode"]:
                errs.append("Account Code is required")
            else:
                resolved_type, obj, err = lk.find(acc_type, n["accountCode"])
                if err:
                    errs.append(err)
                elif resolved_type == "CC":
                    account_id, account_name = obj.id, obj.cc_name
                else:
                    account_id, account_name = obj.id, obj.ledger_name

            if n["remarks"] and not remarks:
                remarks = n["remarks"]

            if side == "Dr" and not errs:
                tot_dr += dr_amt; n_dr += 1
            elif side == "Cr" and not errs:
                tot_cr += cr_amt; n_cr += 1

            out_rows.append({
                "rowNo":        n["rowNo"],
                "voucherRef":   n["voucherRef"],
                "date":         n["date"],
                "drCr":         side or n["drCr"],
                "accountType":  resolved_type or n["accountType"],
                "accountCode":  n["accountCode"],
                "accountId":    account_id,
                "accountName":  account_name,
                # error rows echo raw input so the user can correct it in place
                "debit":        n["debit"]  if errs else (float(dr_amt) if side == "Dr" else 0),
                "credit":       n["credit"] if errs else (float(cr_amt) if side == "Cr" else 0),
                "remarks":      n["remarks"],
                "errors":       errs,
            })

        row_errors = any(r["errors"] for r in out_rows)
        if len(dates) > 1:
            v_errors.append("All rows of a voucher must have the same Date")
        if not row_errors:
            if n_dr == 0:
                v_errors.append("Voucher needs at least one Dr line")
            if n_cr == 0:
                v_errors.append("Voucher needs at least one Cr line")
            if tot_dr != tot_cr:
                v_errors.append(f"Not balanced: Debit {tot_dr:,.2f} ≠ Credit {tot_cr:,.2f} (diff {abs(tot_dr - tot_cr):,.2f})")
        if len(g_rows) > 200:
            v_errors.append("A voucher can have at most 200 lines")

        vouchers.append({
            "voucherRef":  "" if ref.startswith("__row") else ref,
            "date":        _fmt(next(iter(dates))) if len(dates) == 1 else None,
            "remarks":     remarks,
            "totalDebit":  float(tot_dr),
            "totalCredit": float(tot_cr),
            "lineCount":   len(g_rows),
            "valid":       not row_errors and not v_errors,
            "errors":      v_errors,
            "rows":        out_rows,
        })

    return vouchers


def _summary(vouchers):
    valid = [v for v in vouchers if v["valid"]]
    return {
        "totalVouchers":   len(vouchers),
        "validVouchers":   len(valid),
        "invalidVouchers": len(vouchers) - len(valid),
        "totalRows":       sum(v["lineCount"] for v in vouchers),
        "validAmount":     round(sum(v["totalDebit"] for v in valid), 2),
    }


def _precheck(data, user_id):
    project_code = data.get("projectCode")
    if not project_code:
        return None, None, res("projectCode required", [], 400)
    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, None, res("Project not found", [], 404)
    if not is_creator(project_code, _MODULE, user_id):
        return None, None, res("You are not authorized to create journal entries", [], 403)
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return None, None, res("No rows found in the file", [], 400)
    if len(rows) > MAX_ROWS:
        return None, None, res(f"Too many rows ({len(rows)}). Max {MAX_ROWS} per upload — split the file.", [], 400)
    return project, rows, None


# ══════════════════════════════════════════════════════════════════
# PUBLIC: VALIDATE (dry run)
# ══════════════════════════════════════════════════════════════════

def validate_bulk_journal(data, user_id):
    try:
        project, rows, err = _precheck(data, user_id)
        if err:
            return err
        vouchers = _validate(rows, project.client_name)
        if len(vouchers) > MAX_VOUCHERS:
            return res(f"Too many vouchers ({len(vouchers)}). Max {MAX_VOUCHERS} per upload.", [], 400)
        return res("Validated", {"summary": _summary(vouchers), "vouchers": vouchers}, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# PUBLIC: IMPORT (creates valid vouchers as Draft)
# ══════════════════════════════════════════════════════════════════

def import_bulk_journal(data, user_id):
    try:
        project, rows, err = _precheck(data, user_id)
        if err:
            return err
        vouchers = _validate(rows, project.client_name)
        if len(vouchers) > MAX_VOUCHERS:
            return res(f"Too many vouchers ({len(vouchers)}). Max {MAX_VOUCHERS} per upload.", [], 400)

        from app.modules.finance.journal_entry.service import _generate_voucher_no

        created, failed = [], []
        for v in vouchers:
            if not v["valid"]:
                failed.append(v)
                continue
            try:
                entry = JournalEntryMaster(
                    voucher_no      = _generate_voucher_no("new_voucher"),
                    journal_uuid    = str(_uuid.uuid4()),
                    entry_date      = datetime.strptime(v["date"], "%Y-%m-%d").date(),
                    project_code    = project.project_code,
                    entry_mode      = "new_voucher",
                    remarks         = v["remarks"] or None,
                    total_debit     = Decimal(str(v["totalDebit"])),
                    total_credit    = Decimal(str(v["totalCredit"])),
                    workflow_status = "Draft",
                    current_level   = 0,
                    locked          = False,
                    created_by      = user_id,
                )
                db.session.add(entry)
                db.session.flush()
                for sl, r in enumerate(v["rows"], start=1):
                    t = r["accountType"]
                    db.session.add(JournalEntryLine(
                        journal_id    = entry.id,
                        sl_no         = sl,
                        account_type  = t,
                        dr_cr         = r["drCr"],
                        cc_id         = r["accountId"] if t == "CC" else None,
                        vendor_id     = r["accountId"] if t == "Vendor" else None,
                        customer_ref  = r["accountName"] if t == "Customer" else None,
                        debit_amount  = Decimal(str(r["debit"] or 0)),
                        credit_amount = Decimal(str(r["credit"] or 0)),
                    ))
                db.session.commit()
                created.append({
                    "voucherRef":  v["voucherRef"],
                    "id":          entry.id,
                    "voucherNo":   entry.voucher_no,
                    "date":        v["date"],
                    "amount":      v["totalDebit"],
                    "lineCount":   v["lineCount"],
                })
            except Exception as e:
                db.session.rollback()
                v["valid"] = False
                v["errors"] = v["errors"] + [f"Could not save: {e}"]
                failed.append(v)

        msg = f"{len(created)} journal entr{'y' if len(created) == 1 else 'ies'} created as Draft"
        if failed:
            msg += f", {len(failed)} need correction"
        return res(msg, {
            "created": created,
            "failed":  failed,
            "summary": {
                "createdCount": len(created),
                "failedCount":  len(failed),
                "createdAmount": round(sum(c["amount"] for c in created), 2),
            },
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
