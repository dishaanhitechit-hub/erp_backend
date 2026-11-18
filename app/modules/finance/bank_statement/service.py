"""
Bank Statement Import + petty cash docket linking.

Statement format (one row = one bank line; the frontend parses xlsx / xls / csv
into plain rows and posts them here):

    DATE | BY-DR | TO-CR | DR | CR | BALANCE | DESC | CR-DR | SITE | REF NO (optional)

Row payload keys: rowNo, date, byDr, toCr, dr, cr, balance, desc, crDr, site, refNo

* Bank account  = bank_cash (Master > Bank/Cash), type BANK, chosen at upload.
* SITE          = projects.project_code. Blank SITE is allowed (line is stored
                  but never offered to a petty cash docket). A SITE must be a
                  project linked to the bank account.
* Duplicates    = same account + date + direction + amount + balance + DESC +
                  parties + ref → skipped (in DB or earlier in the same file).
* DR = outgoing payment, CR = incoming receipt. Only DR lines can be linked to a
  petty cash expense docket, and only one docket per line.

Permissions: super admin, or bank_statement.VIEW / EDIT in at least one project
linked to the bank account. Linking from a docket uses the docket's own
petty_cash creator rule.
"""

import hashlib
import logging
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import g
from sqlalchemy import func, or_

from app.extensions import db
from app.response import res
from app.models.bankCash import BankCash, BankCashProject
from app.models.bankStatement import BankStatementBatch, BankTransaction, BankTransactionLog
from app.models.project import Project
from app.models.user import User

log = logging.getLogger(__name__)

PAGE = "bank_statement"
MAX_ROWS = 10000
_TWO = Decimal("0.01")

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y",
)
_DIR_ALIASES = {"dr": "DR", "debit": "DR", "d": "DR", "withdrawal": "DR",
                "cr": "CR", "credit": "CR", "c": "CR", "deposit": "CR"}
_UPI_RE = re.compile(r"(?<![A-Z])UPI(?![A-Z])", re.I)


class LinkError(Exception):
    """Business-rule failure while linking a bank transaction to a docket (→ 400)."""


# ══════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════

def _s(v):
    return "" if v is None else str(v).strip()


def _key(v):
    return re.sub(r"[\s_\-./]", "", _s(v).lower())


def _fmt(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _num(d):
    return float(d) if d is not None else None


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


def _parse_amount(v, allow_negative=False):
    """Returns (Decimal|None, error|None). Blank → None."""
    raw = _s(v).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    if raw in ("", "-"):
        return None, None
    neg = False
    if raw.startswith("(") and raw.endswith(")"):
        raw, neg = raw[1:-1], True
    if raw.upper().endswith(("DR", "CR")):        # "300000 CR" style balances
        if raw.upper().endswith("DR"):
            neg = True
        raw = raw[:-2].strip()
    try:
        amt = Decimal(raw)
    except InvalidOperation:
        return None, f"'{_s(v)}' is not a valid number"
    if neg:
        amt = -amt
    if amt < 0 and not allow_negative:
        return None, "cannot be negative"
    return amt.quantize(_TWO, rounding=ROUND_HALF_UP), None


def _norm_text(v):
    return re.sub(r"\s+", " ", _s(v)).upper()


def _dedupe_key(account_id, d, ttype, amount, balance, desc, by_dr, to_cr, ref):
    parts = [str(account_id), _fmt(d), ttype, f"{amount:.2f}",
             "" if balance is None else f"{balance:.2f}",
             _norm_text(desc), _norm_text(by_dr), _norm_text(to_cr), _norm_text(ref)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _is_upi(*texts):
    return any(_UPI_RE.search(t or "") for t in texts)


def _user_id():
    return g.current_user.get("id") if hasattr(g, "current_user") else None


def _username(uid):
    if not uid:
        return None
    u = User.query.get(uid)
    return u.username if u else None


# ── permissions ──────────────────────────────────────────────────

def _is_super(user_id):
    u = User.query.get(user_id) if user_id else None
    return bool(u and u.global_role and u.global_role.name == "super_admin")


def _perm_projects(user_id, action):
    """Project ids where the user holds bank_statement.<action> (EDIT implies VIEW). None = all."""
    if _is_super(user_id):
        return None
    from app.models.project_role import ProjectUserRole
    from app.modules.setting.permission_service import get_user_permissions
    out = set()
    pids = {pid for (pid,) in db.session.query(ProjectUserRole.project_id)
            .filter(ProjectUserRole.user_id == user_id, ProjectUserRole.project_id.isnot(None)).distinct()}
    for pid in pids:
        try:
            perms = get_user_permissions(pid, user_id) or {}
        except Exception:
            db.session.rollback()
            log.warning("permission lookup failed (project %s)", pid, exc_info=True)
            perms = {}
        if perms.get(f"{PAGE}.EDIT") or (action == "VIEW" and perms.get(f"{PAGE}.VIEW")):
            out.add(pid)
    return out


def _account_project_ids(account_id):
    return {pid for (pid,) in db.session.query(BankCashProject.project_id).filter_by(bank_cash_id=account_id)}


def _can_account(user_id, account_id, action):
    allowed = _perm_projects(user_id, action)
    return allowed is None or bool(allowed & _account_project_ids(account_id))


def _allowed_account_ids(user_id, action):
    """None = all accounts (super admin)."""
    allowed = _perm_projects(user_id, action)
    if allowed is None:
        return None
    if not allowed:
        return set()
    return {aid for (aid,) in db.session.query(BankCashProject.bank_cash_id)
            .filter(BankCashProject.project_id.in_(allowed)).distinct()}


def _bank_account(account_id):
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        return None, res("bankAccountId required", [], 400)
    acc = BankCash.query.get(account_id)
    if not acc:
        return None, res("Bank account not found", [], 404)
    if (acc.type or "").upper() != "BANK":
        return None, res(f"{acc.bank_code} is a {acc.type} account — statements can be imported only for BANK accounts", [], 400)
    return acc, None


def _audit(txn, action, user_id, docket=None, note=None):
    db.session.add(BankTransactionLog(
        transaction_id=txn.id,
        docket_id=docket.id if docket is not None else txn.linked_docket_id,
        docket_no=docket.voucher_no if docket is not None else None,
        action=action, note=(note or "")[:255] or None, action_by=user_id,
    ))


def _txn_payload(t, with_link=False):
    out = {
        "id":              t.id,
        "bankAccountId":   t.bank_account_id,
        "bankCode":        t.bank_account.bank_code if t.bank_account else None,
        "batchId":         t.import_batch_id,
        "rowNo":           t.row_no,
        "date":            _fmt(t.transaction_date),
        "byDr":            t.by_dr,
        "toCr":            t.to_cr,
        "dr":              _num(t.debit_amount),
        "cr":              _num(t.credit_amount),
        "balance":         _num(t.balance),
        "desc":            t.description,
        "type":            t.transaction_type,
        "amount":          _num(t.debit_amount if t.transaction_type == "DR" else t.credit_amount),
        "site":            t.site_code,
        "refNo":           t.reference_number,
        "isUpi":           bool(t.is_upi),
        "status":          t.reconciliation_status,
        "reserved":        bool(t.linked_docket_id) and t.reconciliation_status != "Reconciled",
        "linkedDocketId":  t.linked_docket_id,
    }
    if with_link:
        d = t.linked_docket
        out.update({
            "linkedDocketNo":     d.voucher_no if d else None,
            "linkedDocketStatus": d.workflow_status if d else None,
            "reconciledAt":       _fmt(t.reconciled_at),
        })
    return out


# ══════════════════════════════════════════════════════════════════
# VALIDATION (shared by preview + import)
# ══════════════════════════════════════════════════════════════════

def _validate_rows(rows, account):
    linked_sites = {
        code.upper(): code for (code,) in
        db.session.query(Project.project_code)
        .join(BankCashProject, BankCashProject.project_id == Project.id)
        .filter(BankCashProject.bank_cash_id == account.id)
    }
    site_inputs = {_s(r.get("site")).upper() for r in rows if _s(r.get("site"))}
    all_sites = {}
    if site_inputs:
        all_sites = {c.upper(): c for (c,) in db.session.query(Project.project_code)
                     .filter(func.upper(Project.project_code).in_(site_inputs))}

    out, keys = [], []
    for i, r in enumerate(rows, start=1):
        raw = {k: _s(r.get(k)) for k in ("date", "byDr", "toCr", "dr", "cr", "balance", "desc", "crDr", "site", "refNo")}
        errs = []

        d = _parse_date(raw["date"])
        if not raw["date"]:
            errs.append("DATE is required")
        elif not d:
            errs.append(f"Invalid DATE '{raw['date']}' (use DD-MM-YYYY)")

        dr, e1 = _parse_amount(raw["dr"])
        cr, e2 = _parse_amount(raw["cr"])
        bal, e3 = _parse_amount(raw["balance"], allow_negative=True)
        if e1: errs.append(f"DR {e1}")
        if e2: errs.append(f"CR {e2}")
        if e3: errs.append(f"BALANCE {e3}")
        dr = dr or Decimal("0")
        cr = cr or Decimal("0")

        ttype = _DIR_ALIASES.get(_key(raw["crDr"])) if raw["crDr"] else None
        if raw["crDr"] and not ttype:
            errs.append(f"CR-DR must be DR or CR (got '{raw['crDr']}')")
        if not (e1 or e2):
            if dr > 0 and cr > 0:
                errs.append("Fill either DR or CR, not both")
            elif dr == 0 and cr == 0:
                errs.append("DR or CR amount is required")
            else:
                by_amount = "DR" if dr > 0 else "CR"
                if ttype and ttype != by_amount:
                    errs.append(f"CR-DR says {ttype} but the amount is in the {by_amount} column")
                ttype = ttype or by_amount

        site = None
        if raw["site"]:
            su = raw["site"].upper()
            if su in linked_sites:
                site = linked_sites[su]
            elif su in all_sites:
                errs.append(f"SITE '{raw['site']}' is not linked to bank account {account.bank_code} (Master > Bank/Cash)")
            else:
                errs.append(f"SITE '{raw['site']}' not found — use the project code")

        for k, label, n in (("desc", "DESC", 500), ("byDr", "BY-DR", 200), ("toCr", "TO-CR", 200), ("refNo", "REF NO", 100)):
            if len(raw[k]) > n:
                errs.append(f"{label} is longer than {n} characters")

        amount = dr if ttype == "DR" else cr
        key = None
        if not errs:
            key = _dedupe_key(account.id, d, ttype, amount, bal, raw["desc"], raw["byDr"], raw["toCr"], raw["refNo"])
            keys.append(key)

        out.append({
            "rowNo":   r.get("rowNo") or i,
            **raw,
            "status":  "error" if errs else "valid",
            "errors":  errs,
            "_parsed": None if errs else {
                "date": d, "dr": dr, "cr": cr, "balance": bal, "type": ttype, "amount": amount,
                "site": site, "key": key,
                "isUpi": _is_upi(raw["desc"], raw["byDr"], raw["toCr"], raw["refNo"]),
            },
        })

    existing = set()
    for i in range(0, len(keys), 1000):
        chunk = keys[i:i + 1000]
        existing |= {k for (k,) in db.session.query(BankTransaction.dedupe_key)
                     .filter(BankTransaction.bank_account_id == account.id, BankTransaction.dedupe_key.in_(chunk))}
    seen = {}
    for r in out:
        p = r["_parsed"]
        if not p:
            continue
        if p["key"] in existing:
            r["status"] = "duplicate"
            r["errors"] = ["Already imported earlier (same date, amount, balance and description)"]
        elif p["key"] in seen:
            r["status"] = "duplicate"
            r["errors"] = [f"Same as row {seen[p['key']]} in this file"]
        else:
            seen[p["key"]] = r["rowNo"]
        r["type"] = p["type"]
        r["siteCode"] = p["site"]
        r["isUpi"] = p["isUpi"]
        r["parsedDate"] = _fmt(p["date"])
    return out


def _summary(out):
    valid = [r for r in out if r["status"] == "valid"]
    dates = [r["_parsed"]["date"] for r in valid]
    return {
        "totalRows":   len(out),
        "valid":       len(valid),
        "duplicate":   sum(1 for r in out if r["status"] == "duplicate"),
        "error":       sum(1 for r in out if r["status"] == "error"),
        "totalDebit":  float(sum((r["_parsed"]["dr"] for r in valid), Decimal("0"))),
        "totalCredit": float(sum((r["_parsed"]["cr"] for r in valid), Decimal("0"))),
        "noSite":      sum(1 for r in valid if not r["_parsed"]["site"]),
        "fromDate":    _fmt(min(dates)) if dates else None,
        "toDate":      _fmt(max(dates)) if dates else None,
    }


def _public(out):
    return [{k: v for k, v in r.items() if k != "_parsed"} for r in out]


def _precheck(data, user_id, action):
    acc, err = _bank_account(data.get("bankAccountId"))
    if err:
        return None, None, err
    if not _can_account(user_id, acc.id, action):
        return None, None, res("You do not have Bank Statement permission for this account", [], 403)
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return None, None, res("No rows found in the file", [], 400)
    if len(rows) > MAX_ROWS:
        return None, None, res(f"Too many rows ({len(rows)}). Max {MAX_ROWS} per upload — split the file.", [], 400)
    return acc, rows, None


# ══════════════════════════════════════════════════════════════════
# STATEMENT APIs
# ══════════════════════════════════════════════════════════════════

def get_accounts(user_id):
    """BANK accounts the user may work with, with linked sites."""
    try:
        allowed = _allowed_account_ids(user_id, "VIEW")
        q = BankCash.query.filter(func.upper(BankCash.type) == "BANK")
        if allowed is not None:
            if not allowed:
                return res("Accounts fetched", [], 200)
            q = q.filter(BankCash.id.in_(allowed))
        out = []
        for a in q.order_by(BankCash.bank_code).all():
            sites = [c for (c,) in db.session.query(Project.project_code)
                     .join(BankCashProject, BankCashProject.project_id == Project.id)
                     .filter(BankCashProject.bank_cash_id == a.id)
                     .order_by(Project.project_code)]
            out.append({
                "id": a.id, "bankCode": a.bank_code,
                "name": a.bank_holder_name or a.bank_name or "",
                "bankName": a.bank_name, "accountNo": a.bank_account_number,
                "sites": sites,
                "canImport": _can_account(user_id, a.id, "EDIT"),
            })
        return res("Accounts fetched", out, 200)
    except Exception as e:
        return res(str(e), [], 500)


def validate_statement(data, user_id):
    try:
        acc, rows, err = _precheck(data, user_id, "VIEW")
        if err:
            return err
        out = _validate_rows(rows, acc)
        return res("Validated", {"summary": _summary(out), "rows": _public(out)}, 200)
    except Exception as e:
        return res(str(e), [], 500)


def import_statement(data, user_id):
    """All valid, non-duplicate rows are inserted in ONE transaction with the batch."""
    try:
        acc, rows, err = _precheck(data, user_id, "EDIT")
        if err:
            return err
        # serialise imports per account so two users uploading the same file
        # cannot both pass the duplicate check
        db.session.query(BankCash.id).filter(BankCash.id == acc.id).with_for_update().first()

        out = _validate_rows(rows, acc)
        summ = _summary(out)
        valid = [r for r in out if r["status"] == "valid"]
        if not valid:
            db.session.rollback()
            return res("Nothing to import — every row is a duplicate or has errors",
                       {"summary": summ, "rows": _public(out), "batch": None}, 400)

        batch = BankStatementBatch(
            bank_account_id=acc.id,
            file_name=_s(data.get("fileName"))[:255] or None,
            total_rows=summ["totalRows"], imported_count=summ["valid"],
            skipped_count=summ["duplicate"], failed_count=summ["error"],
            from_date=_parse_date(summ["fromDate"]), to_date=_parse_date(summ["toDate"]),
            total_debit=Decimal(str(summ["totalDebit"])), total_credit=Decimal(str(summ["totalCredit"])),
            created_by=user_id,
        )
        db.session.add(batch)
        db.session.flush()
        for r in valid:
            p = r["_parsed"]
            db.session.add(BankTransaction(
                bank_account_id=acc.id, import_batch_id=batch.id, row_no=r["rowNo"] if isinstance(r["rowNo"], int) else None,
                transaction_date=p["date"], by_dr=r["byDr"] or None, to_cr=r["toCr"] or None,
                debit_amount=p["dr"], credit_amount=p["cr"], balance=p["balance"],
                description=r["desc"] or None, transaction_type=p["type"], site_code=p["site"],
                reference_number=r["refNo"] or None, is_upi=p["isUpi"], dedupe_key=p["key"],
                reconciliation_status="Unreconciled", created_by=user_id,
            ))
        db.session.commit()
        for r in valid:
            r["status"] = "imported"
        msg = f"{summ['valid']} imported"
        if summ["duplicate"]:
            msg += f", {summ['duplicate']} skipped as duplicates"
        if summ["error"]:
            msg += f", {summ['error']} failed"
        return res(msg, {"summary": summ, "rows": _public(out), "batch": _batch_payload(batch)}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _batch_payload(b):
    return {
        "id": b.id, "bankAccountId": b.bank_account_id,
        "bankCode": b.bank_account.bank_code if b.bank_account else None,
        "fileName": b.file_name, "totalRows": b.total_rows,
        "imported": b.imported_count, "skipped": b.skipped_count, "failed": b.failed_count,
        "fromDate": _fmt(b.from_date), "toDate": _fmt(b.to_date),
        "totalDebit": _num(b.total_debit), "totalCredit": _num(b.total_credit),
        "status": b.status,
        "createdBy": b.creator.username if b.creator else None, "createdAt": _fmt(b.created_at),
        "revertedBy": b.reverter.username if b.reverter else None, "revertedAt": _fmt(b.reverted_at),
    }


def list_batches(args, user_id):
    try:
        allowed = _allowed_account_ids(user_id, "VIEW")
        q = BankStatementBatch.query
        if args.get("bankAccountId"):
            q = q.filter(BankStatementBatch.bank_account_id == int(args["bankAccountId"]))
        if allowed is not None:
            if not allowed:
                return res("History fetched", [], 200)
            q = q.filter(BankStatementBatch.bank_account_id.in_(allowed))
        batches = q.order_by(BankStatementBatch.id.desc()).limit(500).all()
        linked = dict(db.session.query(BankTransaction.import_batch_id, func.count(BankTransaction.id))
                      .filter(BankTransaction.import_batch_id.in_([b.id for b in batches] or [0]),
                              BankTransaction.linked_docket_id.isnot(None))
                      .group_by(BankTransaction.import_batch_id))
        out = []
        for b in batches:
            p = _batch_payload(b)
            p["linkedCount"] = linked.get(b.id, 0)
            out.append(p)
        return res("History fetched", out, 200)
    except Exception as e:
        return res(str(e), [], 500)


def revert_batch(batch_id, user_id):
    """Undo an import — only while none of its lines is linked to a docket."""
    try:
        b = BankStatementBatch.query.get(batch_id)
        if not b:
            return res("Import not found", [], 404)
        if not _can_account(user_id, b.bank_account_id, "EDIT"):
            return res("You do not have Bank Statement permission for this account", [], 403)
        if b.status == "Reverted":
            return res("Import already reverted", [], 400)
        # lock the batch's lines so no docket can link one while we delete them
        locked = (db.session.query(BankTransaction.id, BankTransaction.linked_docket_id,
                                   BankTransaction.reconciliation_status)
                  .filter(BankTransaction.import_batch_id == b.id).with_for_update().all())
        busy = sum(1 for _, linked, st in locked if linked or st == "Reconciled")
        if busy:
            return res(f"{busy} transaction(s) of this import are linked to petty cash dockets — unlink them first", [], 400)
        n = BankTransaction.query.filter_by(import_batch_id=b.id).delete(synchronize_session=False)
        b.status = "Reverted"
        b.reverted_by = user_id
        b.reverted_at = datetime.utcnow()
        db.session.commit()
        return res(f"Import reverted — {n} transactions removed", _batch_payload(b), 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def list_transactions(args, user_id):
    try:
        allowed = _allowed_account_ids(user_id, "VIEW")
        q = BankTransaction.query
        if allowed is not None:
            if not allowed:
                return res("Transactions fetched", {"list": [], "total": 0}, 200)
            q = q.filter(BankTransaction.bank_account_id.in_(allowed))
        if args.get("bankAccountId"):
            q = q.filter(BankTransaction.bank_account_id == int(args["bankAccountId"]))
        if args.get("batchId"):
            q = q.filter(BankTransaction.import_batch_id == int(args["batchId"]))
        if args.get("site"):
            q = q.filter(func.upper(BankTransaction.site_code) == args["site"].upper())
        if args.get("type") in ("DR", "CR"):
            q = q.filter(BankTransaction.transaction_type == args["type"])
        st = args.get("status")
        if st == "Reconciled":
            q = q.filter(BankTransaction.reconciliation_status == "Reconciled")
        elif st == "Reserved":
            q = q.filter(BankTransaction.reconciliation_status == "Unreconciled", BankTransaction.linked_docket_id.isnot(None))
        elif st == "Unreconciled":
            q = q.filter(BankTransaction.reconciliation_status == "Unreconciled", BankTransaction.linked_docket_id.is_(None))
        if args.get("fromDate"):
            q = q.filter(BankTransaction.transaction_date >= args["fromDate"])
        if args.get("toDate"):
            q = q.filter(BankTransaction.transaction_date <= args["toDate"])
        if args.get("search"):
            t = f"%{args['search']}%"
            q = q.filter(or_(BankTransaction.description.ilike(t), BankTransaction.by_dr.ilike(t),
                             BankTransaction.to_cr.ilike(t), BankTransaction.reference_number.ilike(t)))
        total = q.count()
        page = max(int(args.get("page") or 1), 1)
        size = min(max(int(args.get("pageSize") or 50), 1), 500)
        rows = (q.order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc())
                .offset((page - 1) * size).limit(size).all())
        return res("Transactions fetched", {"list": [_txn_payload(t, with_link=True) for t in rows],
                                            "total": total, "page": page, "pageSize": size}, 200)
    except Exception as e:
        return res(str(e), [], 500)


def transaction_history(txn_id, user_id):
    try:
        t = BankTransaction.query.get(txn_id)
        if not t:
            return res("Transaction not found", [], 404)
        if not _can_account(user_id, t.bank_account_id, "VIEW"):
            return res("Access denied", [], 403)
        logs = BankTransactionLog.query.filter_by(transaction_id=t.id).order_by(BankTransactionLog.id).all()
        return res("History fetched", {
            "transaction": _txn_payload(t, with_link=True),
            "importedBy": _username(t.created_by), "importedAt": _fmt(t.created_at),
            "history": [{"action": l.action, "docketId": l.docket_id, "docketNo": l.docket_no, "note": l.note,
                         "by": l.user.username if l.user else None, "at": _fmt(l.action_at)} for l in logs],
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# PETTY CASH DOCKET — picker + link lifecycle
# ══════════════════════════════════════════════════════════════════

def available_for_docket(args, user_id):
    """Unreconciled DR lines of this site + bank account that no other docket holds."""
    try:
        from app.modules.work_flow import is_creator
        project_code = args.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)
        if not is_creator(project_code, "petty_cash", user_id):
            return res("You are not authorized to create docket vouchers", [], 403)
        acc, err = _bank_account(args.get("bankCashId"))
        if err:
            return err
        project = Project.query.filter_by(project_code=project_code).first()
        if not project or not BankCashProject.query.filter_by(bank_cash_id=acc.id, project_id=project.id).first():
            return res("This account is not linked to the project", [], 400)

        docket_id = int(args["docketId"]) if str(args.get("docketId") or "").isdigit() else None
        q = BankTransaction.query.filter(
            BankTransaction.bank_account_id == acc.id,
            BankTransaction.site_code == project.project_code,        # site filter is mandatory
            BankTransaction.transaction_type == "DR",
            BankTransaction.reconciliation_status == "Unreconciled",
        )
        if docket_id:
            q = q.filter(or_(BankTransaction.linked_docket_id.is_(None), BankTransaction.linked_docket_id == docket_id))
        else:
            q = q.filter(BankTransaction.linked_docket_id.is_(None))
        kind = (args.get("kind") or "all").lower()
        if kind == "upi":
            q = q.filter(BankTransaction.is_upi.is_(True))
        elif kind == "bank":
            q = q.filter(BankTransaction.is_upi.is_(False))
        if args.get("fromDate"):
            q = q.filter(BankTransaction.transaction_date >= args["fromDate"])
        if args.get("toDate"):
            q = q.filter(BankTransaction.transaction_date <= args["toDate"])
        if args.get("search"):
            t = f"%{args['search']}%"
            q = q.filter(or_(BankTransaction.description.ilike(t), BankTransaction.by_dr.ilike(t),
                             BankTransaction.to_cr.ilike(t), BankTransaction.reference_number.ilike(t)))
        rows = q.order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc()).limit(500).all()
        return res("Transactions fetched", {"site": project.project_code, "bankCode": acc.bank_code,
                                            "list": [_txn_payload(t) for t in rows]}, 200)
    except Exception as e:
        return res(str(e), [], 500)


def reserve_for_docket(txn_id, voucher, user_id):
    """Lock + validate + link. Caller commits. Raises LinkError on a rule failure."""
    try:
        txn_id = int(txn_id)
    except (TypeError, ValueError):
        raise LinkError("Invalid bank transaction")
    t = BankTransaction.query.filter_by(id=txn_id).with_for_update().first()
    if not t:
        raise LinkError("Bank transaction not found")
    if (voucher.mode_of_payment or "").lower() == "cash":
        raise LinkError("A Cash docket cannot be linked to a bank transaction")
    if t.transaction_type != "DR":
        raise LinkError("Only DR (outgoing) bank transactions can be linked to an expense docket")
    if t.bank_account_id != voucher.bank_cash_id:
        raise LinkError("The bank transaction belongs to a different bank account than the docket")
    if (t.site_code or "").upper() != (voucher.project_code or "").upper():
        raise LinkError(f"The bank transaction belongs to site {t.site_code or '(none)'}, not {voucher.project_code}")
    if t.reconciliation_status == "Reconciled" and t.linked_docket_id != voucher.id:
        raise LinkError("This bank transaction is already reconciled")
    if t.linked_docket_id and t.linked_docket_id != voucher.id:
        raise LinkError("This bank transaction is already linked to another docket — fetch the list again")
    total = Decimal(str(voucher.total_amount or 0)).quantize(_TWO)
    if total != Decimal(str(t.debit_amount or 0)).quantize(_TWO):
        raise LinkError(f"Docket total {total:,.2f} must equal the bank transaction DR amount {t.debit_amount:,.2f}")
    if t.linked_docket_id != voucher.id:
        t.linked_docket_id = voucher.id
        t.linked_by = user_id
        t.linked_at = datetime.utcnow()
        _audit(t, "LINK", user_id, voucher)
    return t


def release_for_docket(voucher, user_id, note=None):
    """Unlink whatever transaction this docket holds (not if already reconciled). Caller commits."""
    t = BankTransaction.query.filter_by(linked_docket_id=voucher.id).with_for_update().first()
    if not t:
        return None
    if t.reconciliation_status == "Reconciled":
        raise LinkError("The linked bank transaction is already reconciled and cannot be unlinked")
    _audit(t, "UNLINK", user_id, voucher, note)
    t.linked_docket_id = None
    t.linked_by = None
    t.linked_at = None
    return t


def current_txn_id(voucher):
    t = BankTransaction.query.filter_by(linked_docket_id=voucher.id).first()
    return t.id if t else None


def reconcile_for_docket(voucher, user_id):
    """Final approval → Reconciled. Caller commits."""
    t = BankTransaction.query.filter_by(linked_docket_id=voucher.id).with_for_update().first()
    if not t or t.reconciliation_status == "Reconciled":
        return t
    total = Decimal(str(voucher.total_amount or 0)).quantize(_TWO)
    if total != Decimal(str(t.debit_amount or 0)).quantize(_TWO):
        raise LinkError(f"Docket total {total:,.2f} no longer equals the linked bank DR amount {t.debit_amount:,.2f}")
    t.reconciliation_status = "Reconciled"
    t.reconciled_by = user_id
    t.reconciled_at = datetime.utcnow()
    _audit(t, "RECONCILE", user_id, voucher, "Docket final approved")
    return t


def docket_link_payload(voucher):
    t = BankTransaction.query.filter_by(linked_docket_id=voucher.id).first()
    return _txn_payload(t) if t else None
