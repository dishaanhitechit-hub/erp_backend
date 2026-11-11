"""
Unified ledger query service.

All ledger views, Trial Balance, P&L and Balance Sheet read from the
accounting_ledger / accounting_ledger_lines tables through this module.
"""

from datetime import datetime, date as date_type
from decimal import Decimal

from sqlalchemy import func, case, and_, or_, literal_column

from app.extensions import db
from app.models.accounting import AccountingLedger, AccountingLedgerLine, FinancialYear
from app.models.cc_code import CCCode
from app.models.category_group import GroupMaster, SubGroupMaster
from app.models.vendor import Vendor
from app.models.bankCash import BankCash


def _parse_date(s):
    if not s:
        return None
    if isinstance(s, date_type):
        return s
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _d(val):
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


# ── Source type display names ─────────────────────────────────────────────

SOURCE_TYPE_LABELS = {
    "purchase_bill": "Purchase Bill",
    "payment_voucher": "Payment Voucher",
    "bill_payment": "Bill Payment",
    "sale_bill": "Sale Bill",
    "sale_receipt_billing": "Sale Receipt",
    "journal_entry": "Journal Entry",
    "contra_entry": "Contra Entry",
    "debit_note": "Debit Note",
    "credit_note": "Credit Note",
    "petty_cash_docket": "Petty Cash",
    "opening_balance": "Opening Balance",
    "grn": "Goods Received Note",
    "gin": "Goods Issue Note",
}


# ═══════════════════════════════════════════════════════════════════════════
# GENERAL LEDGER — account-wise with running balance
# ═══════════════════════════════════════════════════════════════════════════

def get_general_ledger(params):
    """
    Returns transactions for a specific account with opening balance and
    running balance. Supports all account types: CC, Vendor, BankCash.
    """
    account_type = params.get("account_type")
    account_id = params.get("account_id")
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    if not account_type or not account_id:
        return {"message": "account_type and account_id required", "data": []}, 400

    account_id = int(account_id)

    # Build account filter for lines
    def _acct_filter(q):
        if account_type == "CC":
            q = q.filter(AccountingLedgerLine.account_type == "CC", AccountingLedgerLine.cc_id == account_id)
        elif account_type == "Vendor":
            q = q.filter(AccountingLedgerLine.account_type == "Vendor", AccountingLedgerLine.vendor_id == account_id)
        elif account_type == "BankCash":
            q = q.filter(AccountingLedgerLine.account_type == "BankCash", AccountingLedgerLine.bank_cash_id == account_id)
        return q

    def _project_filter(q):
        if project_code:
            q = q.filter(AccountingLedger.project_code == project_code)
        return q

    # Opening balance: sum of all transactions BEFORE from_date
    opening_dr = Decimal("0")
    opening_cr = Decimal("0")
    if from_date:
        ob_q = db.session.query(
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("dr_sum"),
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("cr_sum"),
        ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
        ob_q = _acct_filter(ob_q)
        ob_q = _project_filter(ob_q)
        ob_q = ob_q.filter(AccountingLedger.posting_date < from_date)
        result = ob_q.first()
        if result:
            opening_dr = _d(result.dr_sum)
            opening_cr = _d(result.cr_sum)

    opening_balance = float(opening_dr - opening_cr)

    # Transactions in period
    txn_q = db.session.query(
        AccountingLedgerLine,
        AccountingLedger.posting_date,
        AccountingLedger.voucher_no,
        AccountingLedger.source_type,
        AccountingLedger.source_id,
        AccountingLedger.project_code,
        AccountingLedger.remarks,
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
    txn_q = _acct_filter(txn_q)
    txn_q = _project_filter(txn_q)
    if from_date:
        txn_q = txn_q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        txn_q = txn_q.filter(AccountingLedger.posting_date <= to_date)
    txn_q = txn_q.order_by(AccountingLedger.posting_date, AccountingLedger.id, AccountingLedgerLine.sl_no)

    running = Decimal(str(opening_balance))
    entries = []
    for line, post_date, voucher_no, src_type, src_id, proj, remark in txn_q.all():
        dr = float(line.amount) if line.dr_cr == "Dr" else 0.0
        cr = float(line.amount) if line.dr_cr == "Cr" else 0.0
        running += Decimal(str(dr)) - Decimal(str(cr))
        entries.append({
            "date": _fmt_date(post_date),
            "voucherNo": voucher_no,
            "sourceType": src_type,
            "sourceTypeLabel": SOURCE_TYPE_LABELS.get(src_type, src_type),
            "sourceId": src_id,
            "projectCode": proj,
            "narration": line.narration or remark or "",
            "debit": dr,
            "credit": cr,
            "balance": float(running),
        })

    # Account name
    account_name = _get_account_name(account_type, account_id)

    closing_balance = float(running)

    return {
        "message": "OK",
        "data": {
            "accountType": account_type,
            "accountId": account_id,
            "accountName": account_name,
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "openingBalance": opening_balance,
            "closingBalance": closing_balance,
            "totalDebit": float(sum(Decimal(str(e["debit"])) for e in entries)),
            "totalCredit": float(sum(Decimal(str(e["credit"])) for e in entries)),
            "entries": entries,
        },
    }, 200


def _get_account_name(account_type, account_id):
    if account_type == "CC":
        cc = CCCode.query.get(account_id)
        return f"{cc.cc_code} - {cc.cc_name}" if cc else str(account_id)
    elif account_type == "Vendor":
        v = Vendor.query.get(account_id)
        return f"{v.ledger_code} - {v.ledger_name}" if v else str(account_id)
    elif account_type == "BankCash":
        bc = BankCash.query.get(account_id)
        return f"{bc.bank_code} - {bc.bank_name or bc.bank_holder_name or ''}" if bc else str(account_id)
    return str(account_id)


# ═══════════════════════════════════════════════════════════════════════════
# TRIAL BALANCE
# ═══════════════════════════════════════════════════════════════════════════

def get_trial_balance(params):
    """
    Trial Balance: all accounts with debit/credit totals.
    """
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    # Query grouped by account_type + account_id
    q = db.session.query(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.cc_id,
        AccountingLedgerLine.vendor_id,
        AccountingLedgerLine.bank_cash_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("total_dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("total_cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)

    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.group_by(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.cc_id,
        AccountingLedgerLine.vendor_id,
        AccountingLedgerLine.bank_cash_id,
    )

    rows = []
    grand_dr = Decimal("0")
    grand_cr = Decimal("0")

    for acct_type, cc_id, vendor_id, bc_id, dr_total, cr_total in q.all():
        dr_total = _d(dr_total)
        cr_total = _d(cr_total)
        net = dr_total - cr_total

        if acct_type == "CC":
            acct_id = cc_id
        elif acct_type == "Vendor":
            acct_id = vendor_id
        elif acct_type == "BankCash":
            acct_id = bc_id
        else:
            acct_id = None

        name = _get_account_name(acct_type, acct_id) if acct_id else "Unknown"

        # Group info for CC accounts
        group_name = None
        head_under = None
        if acct_type == "CC" and cc_id:
            cc = CCCode.query.get(cc_id)
            if cc and cc.group:
                group_name = cc.group.group_name
                head_under = cc.group.head_under

        closing_dr = float(net) if net > 0 else 0.0
        closing_cr = float(abs(net)) if net < 0 else 0.0

        rows.append({
            "accountType": acct_type,
            "accountId": acct_id,
            "accountName": name,
            "groupName": group_name,
            "headUnder": head_under,
            "debit": float(dr_total),
            "credit": float(cr_total),
            "closingDebit": closing_dr,
            "closingCredit": closing_cr,
        })

        grand_dr += dr_total
        grand_cr += cr_total

    rows.sort(key=lambda r: (r["accountType"], r["accountName"]))

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "grandTotalDebit": float(grand_dr),
            "grandTotalCredit": float(grand_cr),
            "rows": rows,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# PROFIT & LOSS
# ═══════════════════════════════════════════════════════════════════════════

def get_profit_loss(params):
    """
    P&L from actual posted income and expense transactions.
    Uses GroupMaster.head_under == 'Profit & Loss'.
    """
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    # Get all CC codes under P&L groups
    pl_groups = GroupMaster.query.filter_by(head_under="Profit & Loss").all()
    pl_group_ids = [g.id for g in pl_groups]

    if not pl_group_ids:
        return {"message": "OK", "data": {"income": [], "expense": [], "netProfit": 0}}, 200

    pl_cc_ids = [
        cc.id for cc in CCCode.query.filter(
            CCCode.group_id.in_(pl_group_ids),
            CCCode.status == "Active",
        ).all()
    ]

    # Also include cc codes that are PL-linked
    pl_linked_ids = [
        cc.id for cc in CCCode.query.filter(
            CCCode.pl_linked == True,
            CCCode.status == "Active",
        ).all()
    ]

    all_pl_ids = list(set(pl_cc_ids + pl_linked_ids))

    if not all_pl_ids:
        return {"message": "OK", "data": {"income": [], "expense": [], "netProfit": 0}}, 200

    # Query ledger lines for PL accounts
    q = db.session.query(
        AccountingLedgerLine.cc_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "CC",
        AccountingLedgerLine.cc_id.in_(all_pl_ids),
    )

    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.group_by(AccountingLedgerLine.cc_id)

    # Build group → sub_group → account hierarchy
    income_groups = {}
    expense_groups = {}
    total_income = Decimal("0")
    total_expense = Decimal("0")

    for cc_id, dr_total, cr_total in q.all():
        cc = CCCode.query.get(cc_id)
        if not cc:
            continue

        dr_total = _d(dr_total)
        cr_total = _d(cr_total)
        net = cr_total - dr_total  # positive = income, negative = expense

        # Use PL group if pl_linked, else use primary group
        if cc.pl_linked and cc.pl_group_id:
            grp = GroupMaster.query.get(cc.pl_group_id)
            sub_grp = SubGroupMaster.query.get(cc.pl_sub_group_id) if cc.pl_sub_group_id else None
        else:
            grp = cc.group
            sub_grp = cc.sub_group

        grp_name = grp.group_name if grp else "Ungrouped"
        sub_grp_name = sub_grp.sub_group_name if sub_grp and hasattr(sub_grp, 'sub_group_name') else None

        row = {
            "ccId": cc.id,
            "ccCode": cc.cc_code,
            "ccName": cc.cc_name,
            "groupName": grp_name,
            "subGroupName": sub_grp_name,
            "debit": float(dr_total),
            "credit": float(cr_total),
            "net": float(net),
        }

        if net >= 0:
            income_groups.setdefault(grp_name, []).append(row)
            total_income += net
        else:
            row["net"] = float(abs(net))
            expense_groups.setdefault(grp_name, []).append(row)
            total_expense += abs(net)

    net_profit = float(total_income - total_expense)

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "income": [{"group": k, "accounts": v, "total": sum(a["net"] for a in v)} for k, v in income_groups.items()],
            "expense": [{"group": k, "accounts": v, "total": sum(a["net"] for a in v)} for k, v in expense_groups.items()],
            "totalIncome": float(total_income),
            "totalExpense": float(total_expense),
            "netProfit": net_profit,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# BALANCE SHEET
# ═══════════════════════════════════════════════════════════════════════════

def get_balance_sheet_report(params):
    """
    Balance Sheet from the central accounting ledger.
    Uses GroupMaster.head_under == 'Balance Sheet'.
    """
    as_of_date = _parse_date(params.get("as_of_date") or params.get("to_date"))
    project_code = params.get("project_code")

    # All CC codes under BS groups
    bs_groups = GroupMaster.query.filter_by(head_under="Balance Sheet").all()
    bs_group_ids = [g.id for g in bs_groups]

    # CC balances
    cc_q = db.session.query(
        AccountingLedgerLine.cc_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "CC",
    )
    if as_of_date:
        cc_q = cc_q.filter(AccountingLedger.posting_date <= as_of_date)
    if project_code:
        cc_q = cc_q.filter(AccountingLedger.project_code == project_code)
    cc_q = cc_q.group_by(AccountingLedgerLine.cc_id)

    # Vendor balances (creditors/debtors)
    vendor_q = db.session.query(
        AccountingLedgerLine.vendor_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "Vendor",
    )
    if as_of_date:
        vendor_q = vendor_q.filter(AccountingLedger.posting_date <= as_of_date)
    if project_code:
        vendor_q = vendor_q.filter(AccountingLedger.project_code == project_code)
    vendor_q = vendor_q.group_by(AccountingLedgerLine.vendor_id)

    # Bank/Cash balances
    bank_q = db.session.query(
        AccountingLedgerLine.bank_cash_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "BankCash",
    )
    if as_of_date:
        bank_q = bank_q.filter(AccountingLedger.posting_date <= as_of_date)
    if project_code:
        bank_q = bank_q.filter(AccountingLedger.project_code == project_code)
    bank_q = bank_q.group_by(AccountingLedgerLine.bank_cash_id)

    # Build asset / liability sections
    assets = []
    liabilities = []
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")

    # CC codes — classify by group
    for cc_id, dr, cr in cc_q.all():
        cc = CCCode.query.get(cc_id) if cc_id else None
        if not cc:
            continue
        if cc.group_id not in bs_group_ids:
            continue

        net = _d(dr) - _d(cr)
        grp = cc.group
        sub_grp = cc.sub_group

        row = {
            "type": "CC",
            "id": cc.id,
            "code": cc.cc_code,
            "name": cc.cc_name,
            "groupName": grp.group_name if grp else "",
            "subGroupName": sub_grp.sub_group_name if sub_grp and hasattr(sub_grp, 'sub_group_name') else None,
            "balance": float(abs(net)),
        }

        if net > 0:
            assets.append(row)
            total_assets += net
        elif net < 0:
            row["balance"] = float(abs(net))
            liabilities.append(row)
            total_liabilities += abs(net)

    # Vendors — creditors (Cr balance) vs debtors (Dr balance)
    sundry_creditors = Decimal("0")
    sundry_debtors = Decimal("0")
    creditor_details = []
    debtor_details = []

    for vid, dr, cr in vendor_q.all():
        v = Vendor.query.get(vid) if vid else None
        if not v:
            continue
        net = _d(dr) - _d(cr)
        row = {
            "type": "Vendor",
            "id": v.id,
            "code": v.ledger_code,
            "name": v.ledger_name,
            "isDebtor": v.is_debtor,
            "balance": float(abs(net)),
        }
        if net < 0:
            sundry_creditors += abs(net)
            creditor_details.append(row)
        elif net > 0:
            sundry_debtors += net
            debtor_details.append(row)

    if sundry_debtors > 0:
        assets.append({
            "type": "Summary",
            "code": "SUNDRY_DEBTORS",
            "name": "Sundry Debtors",
            "balance": float(sundry_debtors),
            "details": debtor_details,
        })
        total_assets += sundry_debtors

    if sundry_creditors > 0:
        liabilities.append({
            "type": "Summary",
            "code": "SUNDRY_CREDITORS",
            "name": "Sundry Creditors",
            "balance": float(sundry_creditors),
            "details": creditor_details,
        })
        total_liabilities += sundry_creditors

    # Bank/Cash
    for bc_id, dr, cr in bank_q.all():
        bc = BankCash.query.get(bc_id) if bc_id else None
        if not bc:
            continue
        net = _d(dr) - _d(cr)
        row = {
            "type": "BankCash",
            "id": bc.id,
            "code": bc.bank_code,
            "name": bc.bank_name or bc.bank_holder_name or "",
            "accountType": bc.type,
            "balance": float(abs(net)),
        }
        if net > 0:
            assets.append(row)
            total_assets += net
        elif net < 0:
            liabilities.append(row)
            total_liabilities += abs(net)

    # P&L result (retained earnings)
    pl_data, _ = get_profit_loss({
        "to_date": _fmt_date(as_of_date),
        "project_code": project_code,
    })
    net_profit = Decimal(str(pl_data["data"]["netProfit"]))

    if net_profit > 0:
        liabilities.append({
            "type": "Summary",
            "code": "NET_PROFIT",
            "name": "Net Profit (Current Period)",
            "balance": float(net_profit),
        })
        total_liabilities += net_profit
    elif net_profit < 0:
        assets.append({
            "type": "Summary",
            "code": "NET_LOSS",
            "name": "Net Loss (Current Period)",
            "balance": float(abs(net_profit)),
        })
        total_assets += abs(net_profit)

    return {
        "message": "OK",
        "data": {
            "asOfDate": _fmt_date(as_of_date),
            "projectCode": project_code,
            "assets": assets,
            "liabilities": liabilities,
            "totalAssets": float(total_assets),
            "totalLiabilities": float(total_liabilities),
            "difference": float(total_assets - total_liabilities),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# VENDOR LEDGER (from central accounting)
# ═══════════════════════════════════════════════════════════════════════════

def get_vendor_ledger_central(params):
    vendor_id = params.get("vendor_id")
    if not vendor_id:
        return {"message": "vendor_id required", "data": []}, 400
    params_copy = dict(params)
    params_copy["account_type"] = "Vendor"
    params_copy["account_id"] = vendor_id
    return get_general_ledger(params_copy)


# ═══════════════════════════════════════════════════════════════════════════
# CUSTOMER (DEBTOR) LEDGER
# ═══════════════════════════════════════════════════════════════════════════

def get_customer_ledger(params):
    vendor_id = params.get("vendor_id")
    if not vendor_id:
        return {"message": "vendor_id (debtor) required", "data": []}, 400
    params_copy = dict(params)
    params_copy["account_type"] = "Vendor"
    params_copy["account_id"] = vendor_id
    return get_general_ledger(params_copy)


# ═══════════════════════════════════════════════════════════════════════════
# BANK LEDGER
# ═══════════════════════════════════════════════════════════════════════════

def get_bank_ledger(params):
    bank_cash_id = params.get("bank_cash_id")
    if not bank_cash_id:
        return {"message": "bank_cash_id required", "data": []}, 400
    params_copy = dict(params)
    params_copy["account_type"] = "BankCash"
    params_copy["account_id"] = bank_cash_id
    return get_general_ledger(params_copy)


# ═══════════════════════════════════════════════════════════════════════════
# CC-CODE LEDGER (Cost Centre / Account Ledger)
# ═══════════════════════════════════════════════════════════════════════════

def get_cc_ledger(params):
    cc_id = params.get("cc_id")
    if not cc_id:
        return {"message": "cc_id required", "data": []}, 400
    params_copy = dict(params)
    params_copy["account_type"] = "CC"
    params_copy["account_id"] = cc_id
    return get_general_ledger(params_copy)


# ═══════════════════════════════════════════════════════════════════════════
# DAY BOOK
# ═══════════════════════════════════════════════════════════════════════════

def get_day_book(params):
    target_date = _parse_date(params.get("date") or params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    if not target_date:
        return {"message": "date or from_date required", "data": []}, 400

    q = db.session.query(AccountingLedger)
    if to_date and to_date != target_date:
        q = q.filter(AccountingLedger.posting_date >= target_date,
                      AccountingLedger.posting_date <= to_date)
    else:
        q = q.filter(AccountingLedger.posting_date == target_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    q = q.order_by(AccountingLedger.id)

    entries = []
    for posting in q.all():
        lines_data = []
        for line in posting.lines:
            lines_data.append({
                "slNo": line.sl_no,
                "accountType": line.account_type,
                "accountName": _get_account_name(line.account_type,
                    line.cc_id or line.vendor_id or line.bank_cash_id),
                "drCr": line.dr_cr,
                "amount": float(line.amount),
                "narration": line.narration,
            })

        entries.append({
            "postingId": posting.id,
            "date": _fmt_date(posting.posting_date),
            "voucherNo": posting.voucher_no,
            "sourceType": posting.source_type,
            "sourceTypeLabel": SOURCE_TYPE_LABELS.get(posting.source_type, posting.source_type),
            "sourceId": posting.source_id,
            "projectCode": posting.project_code,
            "totalDebit": float(posting.total_debit),
            "totalCredit": float(posting.total_credit),
            "remarks": posting.remarks,
            "lines": lines_data,
        })

    return {
        "message": "OK",
        "data": {
            "date": _fmt_date(target_date),
            "projectCode": project_code,
            "entries": entries,
            "totalDebit": sum(e["totalDebit"] for e in entries),
            "totalCredit": sum(e["totalCredit"] for e in entries),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# VOUCHER REGISTER
# ═══════════════════════════════════════════════════════════════════════════

def get_voucher_register(params):
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")
    source_type = params.get("source_type")

    q = AccountingLedger.query
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    if source_type:
        q = q.filter(AccountingLedger.source_type == source_type)
    q = q.order_by(AccountingLedger.posting_date, AccountingLedger.id)

    entries = []
    for posting in q.all():
        entries.append({
            "postingId": posting.id,
            "date": _fmt_date(posting.posting_date),
            "voucherNo": posting.voucher_no,
            "sourceType": posting.source_type,
            "sourceTypeLabel": SOURCE_TYPE_LABELS.get(posting.source_type, posting.source_type),
            "sourceId": posting.source_id,
            "projectCode": posting.project_code,
            "totalDebit": float(posting.total_debit),
            "totalCredit": float(posting.total_credit),
            "isReversal": posting.is_reversal,
            "remarks": posting.remarks,
        })

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "entries": entries,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# OUTSTANDING RECEIVABLES / PAYABLES
# ═══════════════════════════════════════════════════════════════════════════

def get_outstanding_payables(params):
    """Vendors with net credit (we owe them)."""
    as_of_date = _parse_date(params.get("as_of_date") or params.get("to_date"))
    project_code = params.get("project_code")

    q = db.session.query(
        AccountingLedgerLine.vendor_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "Vendor",
    )
    if as_of_date:
        q = q.filter(AccountingLedger.posting_date <= as_of_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    q = q.group_by(AccountingLedgerLine.vendor_id)

    rows = []
    total = Decimal("0")
    for vid, dr, cr in q.all():
        net = _d(cr) - _d(dr)
        if net <= 0:
            continue
        v = Vendor.query.get(vid)
        if not v or v.is_debtor:
            continue
        rows.append({
            "vendorId": v.id,
            "ledgerCode": v.ledger_code,
            "ledgerName": v.ledger_name,
            "outstanding": float(net),
        })
        total += net

    rows.sort(key=lambda r: r["outstanding"], reverse=True)

    return {
        "message": "OK",
        "data": {
            "asOfDate": _fmt_date(as_of_date),
            "rows": rows,
            "total": float(total),
        },
    }, 200


def get_outstanding_receivables(params):
    """Debtors (customers) with net debit (they owe us)."""
    as_of_date = _parse_date(params.get("as_of_date") or params.get("to_date"))
    project_code = params.get("project_code")

    q = db.session.query(
        AccountingLedgerLine.vendor_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.account_type == "Vendor",
    )
    if as_of_date:
        q = q.filter(AccountingLedger.posting_date <= as_of_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    q = q.group_by(AccountingLedgerLine.vendor_id)

    rows = []
    total = Decimal("0")
    for vid, dr, cr in q.all():
        net = _d(dr) - _d(cr)
        if net <= 0:
            continue
        v = Vendor.query.get(vid)
        if not v or not v.is_debtor:
            continue
        rows.append({
            "vendorId": v.id,
            "ledgerCode": v.ledger_code,
            "ledgerName": v.ledger_name,
            "outstanding": float(net),
        })
        total += net

    rows.sort(key=lambda r: r["outstanding"], reverse=True)

    return {
        "message": "OK",
        "data": {
            "asOfDate": _fmt_date(as_of_date),
            "rows": rows,
            "total": float(total),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# GST SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def get_gst_summary(params):
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    q = db.session.query(
        AccountingLedgerLine.gst_type,
        AccountingLedgerLine.dr_cr,
        func.sum(AccountingLedgerLine.amount).label("total"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedgerLine.gst_type.isnot(None),
    )
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    q = q.group_by(AccountingLedgerLine.gst_type, AccountingLedgerLine.dr_cr)

    input_gst = {}
    output_gst = {}
    for gst_type, dr_cr, total in q.all():
        total = float(total or 0)
        if dr_cr == "Dr":
            input_gst[gst_type] = input_gst.get(gst_type, 0) + total
        else:
            output_gst[gst_type] = output_gst.get(gst_type, 0) + total

    total_input = sum(input_gst.values())
    total_output = sum(output_gst.values())

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "input": input_gst,
            "output": output_gst,
            "totalInput": total_input,
            "totalOutput": total_output,
            "netPayable": total_output - total_input,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# PROJECT FINANCIAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def get_project_summary(params):
    project_code = params.get("project_code")
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))

    if not project_code:
        return {"message": "project_code required", "data": []}, 400

    # Total income (Cr to revenue CC codes)
    # Total expense (Dr to expense CC codes)
    # Bank/Cash inflows/outflows
    # Net position

    q = db.session.query(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.dr_cr,
        func.sum(AccountingLedgerLine.amount).label("total"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        AccountingLedger.project_code == project_code,
    )
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    q = q.group_by(AccountingLedgerLine.account_type, AccountingLedgerLine.dr_cr)

    summary = {}
    for acct_type, dr_cr, total in q.all():
        key = f"{acct_type}_{dr_cr}"
        summary[key] = float(total or 0)

    return {
        "message": "OK",
        "data": {
            "projectCode": project_code,
            "ccDebit": summary.get("CC_Dr", 0),
            "ccCredit": summary.get("CC_Cr", 0),
            "vendorDebit": summary.get("Vendor_Dr", 0),
            "vendorCredit": summary.get("Vendor_Cr", 0),
            "bankDebit": summary.get("BankCash_Dr", 0),
            "bankCredit": summary.get("BankCash_Cr", 0),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# GROUP-WISE LEDGER
# ═══════════════════════════════════════════════════════════════════════════

def get_group_ledger(params):
    """Summary by GroupMaster for all CC accounts."""
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    q = db.session.query(
        CCCode.group_id,
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("dr"),
        func.coalesce(func.sum(case(
            (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
            else_=literal_column("0"),
        )), 0).label("cr"),
    ).join(AccountingLedgerLine, AccountingLedgerLine.cc_id == CCCode.id
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).filter(AccountingLedgerLine.account_type == "CC")

    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.group_by(CCCode.group_id)

    rows = []
    for gid, dr, cr in q.all():
        grp = GroupMaster.query.get(gid) if gid else None
        net = float(_d(dr) - _d(cr))
        rows.append({
            "groupId": gid,
            "groupName": grp.group_name if grp else "Ungrouped",
            "headUnder": grp.head_under if grp else None,
            "debit": float(dr),
            "credit": float(cr),
            "net": net,
        })

    rows.sort(key=lambda r: r["groupName"])

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "rows": rows,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# FINANCIAL YEAR MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def list_financial_years():
    years = FinancialYear.query.order_by(FinancialYear.start_date.desc()).all()
    return {
        "message": "OK",
        "data": [{
            "id": fy.id,
            "fyCode": fy.fy_code,
            "startDate": _fmt_date(fy.start_date),
            "endDate": _fmt_date(fy.end_date),
            "isLocked": fy.is_locked,
            "isCurrent": fy.is_current,
        } for fy in years],
    }, 200


def create_financial_year(data, user_id):
    from datetime import date as date_type

    fy_code = data.get("fy_code")
    start_date = _parse_date(data.get("start_date"))
    end_date = _parse_date(data.get("end_date"))

    if not fy_code or not start_date or not end_date:
        return {"message": "fy_code, start_date, end_date required", "data": []}, 400

    existing = FinancialYear.query.filter_by(fy_code=fy_code).first()
    if existing:
        return {"message": f"FY {fy_code} already exists", "data": []}, 409

    fy = FinancialYear(
        fy_code=fy_code,
        start_date=start_date,
        end_date=end_date,
        created_by=user_id,
    )
    db.session.add(fy)
    db.session.commit()

    return {"message": f"Financial Year {fy_code} created", "data": {"id": fy.id}}, 201
