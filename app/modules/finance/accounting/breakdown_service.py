"""
"How is this value made?" — Group Ledger breakdown.

A Group Ledger row (e.g. Sundry Creditors, Direct Expenses) opens to show:

    * every account in that group (CC code / bank-cash / vendor) with its
      Dr / Cr / net, and
    * the same total split by document type (Purchase Bill, Payment, JV ...).

Each account then opens in the existing account reconciliation popup
(get_reconciliation) for the voucher-by-voucher list.

The grouping rules mirror get_group_ledger exactly and, like every report,
cancelled originals and their reversals are counted (they net to zero), so
the accounts always add up to the number the user clicked.
"""

from decimal import Decimal

from sqlalchemy import func, case, literal_column, and_, or_

from app.extensions import db
from app.models.accounting import AccountingLedger, AccountingLedgerLine
from app.models.cc_code import CCCode
from app.models.category_group import GroupMaster
from app.models.vendor import Vendor
from app.models.bankCash import BankCash

from .ledger_service import _parse_date, _d, _fmt_date, SOURCE_TYPE_LABELS

# Group Ledger rows for vendors have no GroupMaster id
VENDOR_GROUP_KEYS = {
    "SUNDRY_CREDITORS": ("Sundry Creditors", False),
    "SUNDRY_DEBTORS": ("Sundry Debtors", True),
}


def _dr():
    return func.coalesce(func.sum(case(
        (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
        else_=literal_column("0"),
    )), 0)


def _cr():
    return func.coalesce(func.sum(case(
        (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
        else_=literal_column("0"),
    )), 0)


def _base(*cols):
    return db.session.query(*cols).join(
        AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)


def _group_line_filter(group_id=None, group_key=None):
    """Ledger lines that make up one Group Ledger row. Mirrors get_group_ledger:
    CC -> pl_group_id when P&L-linked, else group_id; bank/cash -> its
    group_id; vendors -> Sundry Debtors / Creditors by the is_debtor flag."""
    if group_key:
        _, is_debtor = VENDOR_GROUP_KEYS[group_key]
        debtor_ids = db.session.query(Vendor.id).filter(Vendor.is_debtor.is_(True))
        if is_debtor:
            cond = AccountingLedgerLine.vendor_id.in_(debtor_ids)
        else:  # everything else, incl. a missing vendor, is a creditor there
            cond = or_(AccountingLedgerLine.vendor_id.is_(None),
                       ~AccountingLedgerLine.vendor_id.in_(debtor_ids))
        return and_(AccountingLedgerLine.account_type == "Vendor", cond)

    pl_override = and_(CCCode.pl_linked.is_(True), CCCode.pl_group_id.isnot(None))
    cc_ids = db.session.query(CCCode.id).filter(or_(
        and_(pl_override, CCCode.pl_group_id == group_id),
        and_(~pl_override, CCCode.group_id == group_id),
    ))
    bank_ids = db.session.query(BankCash.id).filter(BankCash.group_id == group_id)
    return or_(
        and_(AccountingLedgerLine.account_type == "CC", AccountingLedgerLine.cc_id.in_(cc_ids)),
        and_(AccountingLedgerLine.account_type == "BankCash",
             AccountingLedgerLine.bank_cash_id.in_(bank_ids)),
    )


def _bad(msg):
    return {"message": msg, "data": None}, 400


def get_group_breakdown(params):
    group_key = (params.get("group_key") or "").strip().upper() or None
    group_id = None
    if group_key:
        if group_key not in VENDOR_GROUP_KEYS:
            return _bad("Unknown group_key")
    else:
        try:
            group_id = int(params.get("group_id"))
        except (TypeError, ValueError):
            return _bad("group_id or group_key required")

    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code") or None
    filters = [_group_line_filter(group_id, group_key)]
    if from_date:
        filters.append(AccountingLedger.posting_date >= from_date)
    if to_date:
        filters.append(AccountingLedger.posting_date <= to_date)
    if project_code:
        filters.append(AccountingLedger.project_code == project_code)

    # ── accounts in the group ──
    rows = _base(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.cc_id,
        AccountingLedgerLine.vendor_id,
        AccountingLedgerLine.bank_cash_id,
        func.count(func.distinct(AccountingLedger.id)),
        _dr(), _cr(),
    ).filter(*filters).group_by(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.cc_id,
        AccountingLedgerLine.vendor_id,
        AccountingLedgerLine.bank_cash_id,
    ).all()

    cc_ids = {r[1] for r in rows if r[0] == "CC" and r[1]}
    v_ids = {r[2] for r in rows if r[0] == "Vendor" and r[2]}
    bc_ids = {r[3] for r in rows if r[0] == "BankCash" and r[3]}
    ccs = {c.id: c for c in CCCode.query.filter(CCCode.id.in_(cc_ids)).all()} if cc_ids else {}
    vs = {v.id: v for v in Vendor.query.filter(Vendor.id.in_(v_ids)).all()} if v_ids else {}
    bcs = {b.id: b for b in BankCash.query.filter(BankCash.id.in_(bc_ids)).all()} if bc_ids else {}

    accounts = []
    tot_dr = tot_cr = Decimal("0")
    for acct_type, cc_id, v_id, bc_id, n, dr, cr in rows:
        dr, cr = _d(dr), _d(cr)
        tot_dr += dr
        tot_cr += cr
        acct_id, code, name = None, None, "Unknown"
        if acct_type == "CC":
            acct_id, o = cc_id, ccs.get(cc_id)
            code, name = (o.cc_code, o.cc_name) if o else (None, f"CC #{cc_id}")
        elif acct_type == "Vendor":
            acct_id, o = v_id, vs.get(v_id)
            code, name = (o.ledger_code, o.ledger_name) if o else (None, "Unknown vendor")
        elif acct_type == "BankCash":
            acct_id, o = bc_id, bcs.get(bc_id)
            code, name = ((o.bank_code, o.bank_name or o.bank_holder_name or "") if o
                          else (None, f"Bank #{bc_id}"))
        accounts.append({
            "accountType": acct_type,
            "accountId": acct_id,
            "code": code,
            "name": name,
            "vouchers": int(n or 0),
            "debit": float(dr),
            "credit": float(cr),
            "net": float(dr - cr),
        })
    accounts.sort(key=lambda a: (-abs(a["net"]), a["name"] or ""))

    # ── same total split by document type ──
    by_type = []
    for st, n, dr, cr in _base(
        AccountingLedger.source_type,
        func.count(func.distinct(AccountingLedger.id)),
        _dr(), _cr(),
    ).filter(*filters).group_by(AccountingLedger.source_type).all():
        dr, cr = _d(dr), _d(cr)
        by_type.append({
            "sourceType": st,
            "sourceTypeLabel": SOURCE_TYPE_LABELS.get(st) or (st or "").replace("_", " ").title(),
            "count": int(n or 0),
            "debit": float(dr),
            "credit": float(cr),
            "net": float(dr - cr),
        })
    by_type.sort(key=lambda r: -(r["debit"] + r["credit"]))

    if group_key:
        title, head_under = VENDOR_GROUP_KEYS[group_key][0], "Balance Sheet"
    else:
        g = GroupMaster.query.get(group_id)
        title = g.group_name if g else f"Group #{group_id}"
        head_under = g.head_under if g else None

    return {"message": "OK", "data": {
        "groupId": group_id,
        "groupKey": group_key,
        "groupName": title,
        "headUnder": head_under,
        "fromDate": _fmt_date(from_date),
        "toDate": _fmt_date(to_date),
        "projectCode": project_code,
        "totalDebit": float(tot_dr),
        "totalCredit": float(tot_cr),
        "net": float(tot_dr - tot_cr),
        "accounts": accounts,
        "bySourceType": by_type,
    }}, 200
