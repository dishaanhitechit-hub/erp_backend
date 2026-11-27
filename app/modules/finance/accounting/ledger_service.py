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


# ── Cancelled / reversed entries ───────────────────────────────────────────
# A cancelled (or rebacked) document leaves two postings in the ledger: the
# original (is_reversed=TRUE) and its reversal (is_reversal=TRUE). They net to
# zero and share the posting date, so line-level screens hide BOTH by default
# — balances and totals stay correct — and show them (struck through in the
# UI) only when ?include_cancelled=true.

def _include_cancelled(params):
    return str(params.get("include_cancelled") or "").strip().lower() in ("1", "true", "yes")


def _not_cancelled():
    """SQL filter: postings that are in the books (not part of a cancelled pair)."""
    return and_(AccountingLedger.is_reversal.is_(False), AccountingLedger.is_reversed.is_(False))


def _cancelled():
    return or_(AccountingLedger.is_reversal.is_(True), AccountingLedger.is_reversed.is_(True))


def _cancel_flags(is_reversal, is_reversed):
    """(isCancelled, cancelLabel) for one posting."""
    if is_reversal:
        return True, "Reversal entry"
    if is_reversed:
        return True, "Cancelled / reversed"
    return False, None


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


# ── Source type display names ─────────────────────────────────────────────

# ── P&L income / expense group classification ──────────────────────────────
# Groups whose name contains any of these words are treated as income groups.
# Keyword match is intentionally broad to cover Indian-accounting conventions
# (Tally names "Direct Income", "Indirect Income", "Sales A/c", etc.) until a
# `group_nature` column is added to GroupMaster (schema change, pending).
_PL_INCOME_KEYWORDS = frozenset({
    "revenue", "income", "sales", "receipt", "receipts",
    "turnover", "trading", "other income",
})

# ── Balance Sheet asset / liability group classification ───────────────────
# Groups whose name contains any of these words are placed on the asset side.
_BS_ASSET_KEYWORDS = frozenset({
    "asset", "stock", "receivable", "advance paid", "advance given",
    "deposit", "prepaid", "cash", "investment", "loan given",
    "work in progress", "wip", "capital work", "inventory",
    "debtors", "debtor",
})

SOURCE_TYPE_LABELS = {
    "purchase_bill": "Purchase Bill",
    "payment_voucher": "Payment Voucher",
    "bill_payment": "Bill Payment",
    "advance_adjustment": "Advance Adjustment",
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
    "sale_claim_bill": "Sale Claim Bill",
    "sale_certified_bill": "Sale Certified Bill",
    "uncertified_statement": "Uncertified Statement",
}


# Source type → document view page, opened as /<route>/<source_id>. Types
# with no view page of their own (bill_payment, advance_adjustment,
# opening_balance) get no link rather than a wrong one.
SOURCE_DOC_ROUTES = {
    "purchase_bill": "/finance-management/account/purchases/bill",
    "payment_voucher": "/finance-management/account/payment",
    "sale_bill": "/finance-management/account/sale",
    "sale_receipt_billing": "/finance-management/account/receipt-billing",
    "journal_entry": "/finance-management/account/journal",
    "contra_entry": "/finance-management/account/contra",
    "debit_note": "/finance-management/account/debit-note",
    "credit_note": "/finance-management/account/credit-note",
    "petty_cash_docket": "/finance-management/account/petty-cash/expenses-docket",
    "grn": "/resource-management/material/grn",
    "gin": "/resource-management/material/gin",
    "sale_claim_bill": "/project-management/customer-billing/sale-bill-claim",
    "sale_certified_bill": "/project-management/customer-billing/sale-bill-certified",
    "uncertified_statement": "/project-management/customer-billing/uncertified-statement",
}


def _doc_link(source_type, source_id):
    route = SOURCE_DOC_ROUTES.get(source_type)
    return f"{route}/{source_id}" if route and source_id else None


# ═══════════════════════════════════════════════════════════════════════════
# GENERAL LEDGER — account-wise with running balance
# ═══════════════════════════════════════════════════════════════════════════

def _build_particulars_map(posting_ids, current_account_type, current_account_id):
    """
    For a set of posting_ids, find the counterparty accounts —
    the OTHER lines in each posting that are not the current account.
    Returns {posting_id: "counterparty name(s)"}.

    This gives the Tally-style "Particulars" column showing what account
    the money went to/from (e.g. "ICICI BANK_XXX912", "TDS on Sale").
    """
    if not posting_ids:
        return {}

    posting_id_list = list(posting_ids)

    # Batch query: all lines for these postings, excluding the current account's lines
    counter_q = db.session.query(
        AccountingLedgerLine.posting_id,
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.cc_id,
        AccountingLedgerLine.vendor_id,
        AccountingLedgerLine.bank_cash_id,
    ).filter(AccountingLedgerLine.posting_id.in_(posting_id_list))

    # Exclude lines belonging to the current account
    if current_account_type == "CC":
        counter_q = counter_q.filter(
            ~((AccountingLedgerLine.account_type == "CC") &
              (AccountingLedgerLine.cc_id == current_account_id))
        )
    elif current_account_type == "Vendor":
        counter_q = counter_q.filter(
            ~((AccountingLedgerLine.account_type == "Vendor") &
              (AccountingLedgerLine.vendor_id == current_account_id))
        )
    elif current_account_type == "BankCash":
        counter_q = counter_q.filter(
            ~((AccountingLedgerLine.account_type == "BankCash") &
              (AccountingLedgerLine.bank_cash_id == current_account_id))
        )

    counter_lines = counter_q.all()

    # Collect unique account references we need to resolve
    cc_ids = set()
    vendor_ids = set()
    bc_ids = set()
    for _, acct_type, cc_id, vendor_id, bc_id in counter_lines:
        if acct_type == "CC" and cc_id:
            cc_ids.add(cc_id)
        elif acct_type == "Vendor" and vendor_id:
            vendor_ids.add(vendor_id)
        elif acct_type == "BankCash" and bc_id:
            bc_ids.add(bc_id)

    # Bulk-load account names
    cc_names = {}
    if cc_ids:
        for cc in CCCode.query.filter(CCCode.id.in_(list(cc_ids))).all():
            cc_names[cc.id] = cc.cc_name

    vendor_names = {}
    if vendor_ids:
        for v in Vendor.query.filter(Vendor.id.in_(list(vendor_ids))).all():
            vendor_names[v.id] = v.ledger_name

    bc_names = {}
    if bc_ids:
        for bc in BankCash.query.filter(BankCash.id.in_(list(bc_ids))).all():
            bc_names[bc.id] = bc.bank_name or bc.bank_holder_name or bc.bank_code

    # Build posting_id → set of unique counterparty names
    posting_counterparties = {}
    for pid, acct_type, cc_id, vendor_id, bc_id in counter_lines:
        name = None
        if acct_type == "CC" and cc_id:
            name = cc_names.get(cc_id)
        elif acct_type == "Vendor" and vendor_id:
            name = vendor_names.get(vendor_id)
        elif acct_type == "BankCash" and bc_id:
            name = bc_names.get(bc_id)
        if name:
            posting_counterparties.setdefault(pid, [])
            if name not in posting_counterparties[pid]:
                posting_counterparties[pid].append(name)

    # Join multiple counterparties with newline/comma
    result = {}
    for pid, names in posting_counterparties.items():
        result[pid] = ", ".join(names) if len(names) <= 3 else f"{names[0]} & {len(names)-1} others"
    return result


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
    include_cancelled = _include_cancelled(params)

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

    def _cancel_filter(q):
        # pairs net to zero, so hiding them changes no balance
        return q if include_cancelled else q.filter(_not_cancelled())

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
        ob_q = _cancel_filter(ob_q)
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
        AccountingLedger.is_reversal,
        AccountingLedger.is_reversed,
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
    txn_q = _acct_filter(txn_q)
    txn_q = _project_filter(txn_q)
    if from_date:
        txn_q = txn_q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        txn_q = txn_q.filter(AccountingLedger.posting_date <= to_date)

    # how many cancelled lines the default view hides (for the "show" toggle)
    hidden_q = _project_filter(_acct_filter(
        db.session.query(func.count(AccountingLedgerLine.id))
        .join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)))
    if from_date:
        hidden_q = hidden_q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        hidden_q = hidden_q.filter(AccountingLedger.posting_date <= to_date)
    cancelled_count = hidden_q.filter(_cancelled()).scalar() or 0

    txn_q = _cancel_filter(txn_q)
    txn_q = txn_q.order_by(AccountingLedger.posting_date, AccountingLedger.id, AccountingLedgerLine.sl_no)

    running = Decimal(str(opening_balance))
    raw_entries = []
    posting_ids = set()
    for line, post_date, voucher_no, src_type, src_id, proj, remark, is_rev, is_revd in txn_q.all():
        dr = float(line.amount) if line.dr_cr == "Dr" else 0.0
        cr = float(line.amount) if line.dr_cr == "Cr" else 0.0
        running += Decimal(str(dr)) - Decimal(str(cr))
        posting_ids.add(line.posting_id)
        is_cancelled, cancel_label = _cancel_flags(is_rev, is_revd)
        raw_entries.append({
            "isCancelled": is_cancelled,
            "cancelLabel": cancel_label,
            "posting_id": line.posting_id,
            "line_id": line.id,
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

    # Bulk-load counterparty names from the other lines in each posting
    particulars_map = _build_particulars_map(
        posting_ids, account_type, account_id
    )

    entries = []
    for e in raw_entries:
        e["particulars"] = particulars_map.get(e["posting_id"], "")
        del e["posting_id"]
        del e["line_id"]
        entries.append(e)

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
            "includeCancelled": include_cancelled,
            "cancelledCount": cancelled_count,
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
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id).filter(
        _not_cancelled(),
    )

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

    raw_rows = q.all()

    # Bulk-load all lookup tables to avoid N+1 queries
    tb_cc_ids = {r[1] for r in raw_rows if r[0] == "CC" and r[1]}
    tb_vendor_ids = {r[2] for r in raw_rows if r[0] == "Vendor" and r[2]}
    tb_bc_ids = {r[3] for r in raw_rows if r[0] == "BankCash" and r[3]}

    cc_cache = {}
    cc_group_cache = {}
    if tb_cc_ids:
        for cc in CCCode.query.filter(CCCode.id.in_(list(tb_cc_ids))).all():
            cc_cache[cc.id] = cc
            if cc.group_id and cc.group_id not in cc_group_cache:
                cc_group_cache[cc.group_id] = None
        if cc_group_cache:
            for grp in GroupMaster.query.filter(GroupMaster.id.in_(list(cc_group_cache.keys()))).all():
                cc_group_cache[grp.id] = grp

    vendor_cache = {}
    if tb_vendor_ids:
        for v in Vendor.query.filter(Vendor.id.in_(list(tb_vendor_ids))).all():
            vendor_cache[v.id] = v

    bc_cache = {}
    if tb_bc_ids:
        for bc in BankCash.query.filter(BankCash.id.in_(list(tb_bc_ids))).all():
            bc_cache[bc.id] = bc

    def _cached_name(acct_type, acct_id):
        if acct_type == "CC":
            cc = cc_cache.get(acct_id)
            return f"{cc.cc_code} - {cc.cc_name}" if cc else str(acct_id)
        elif acct_type == "Vendor":
            v = vendor_cache.get(acct_id)
            return f"{v.ledger_code} - {v.ledger_name}" if v else str(acct_id)
        elif acct_type == "BankCash":
            bc = bc_cache.get(acct_id)
            return f"{bc.bank_code} - {bc.bank_name or bc.bank_holder_name or ''}" if bc else str(acct_id)
        return str(acct_id)

    rows = []
    grand_dr = Decimal("0")
    grand_cr = Decimal("0")

    for acct_type, cc_id, vendor_id, bc_id, dr_total, cr_total in raw_rows:
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

        name = _cached_name(acct_type, acct_id) if acct_id else "Unknown"

        group_name = None
        head_under = None
        if acct_type == "CC" and cc_id:
            cc = cc_cache.get(cc_id)
            if cc and cc.group_id:
                grp = cc_group_cache.get(cc.group_id)
                if grp:
                    group_name = grp.group_name
                    head_under = grp.head_under

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

def _build_subgroup_tree(accounts_by_subgroup, all_subgroups_map):
    """
    Build a nested tree from SubGroupMaster hierarchy.
    accounts_by_subgroup: {sub_group_id: [account_rows]}
    all_subgroups_map: {id: SubGroupMaster}
    Returns list of top-level nodes (level-0 sub-groups or ungrouped accounts).
    Each node: {type, subGroupId, subGroupName, children, accounts, total}
    """
    # Collect all sub-group IDs that have accounts (directly or via descendants)
    sg_ids_with_data = set()
    for sg_id in accounts_by_subgroup:
        if sg_id and sg_id in all_subgroups_map:
            node = all_subgroups_map[sg_id]
            while node:
                sg_ids_with_data.add(node.id)
                node = all_subgroups_map.get(node.parent_id) if node.parent_id else None

    # Build children map
    children_map = {}  # parent_id -> [SubGroupMaster]
    roots = []  # level-0 sub-groups
    for sg_id in sg_ids_with_data:
        sg = all_subgroups_map[sg_id]
        if sg.parent_id:
            children_map.setdefault(sg.parent_id, []).append(sg)
        else:
            roots.append(sg)

    roots.sort(key=lambda s: (s.fixed_code or "", s.sub_group_name))
    for k in children_map:
        children_map[k].sort(key=lambda s: (s.fixed_code or "", s.sub_group_name))

    def _build_node(sg):
        direct_accounts = sorted(accounts_by_subgroup.get(sg.id, []), key=lambda a: a.get("ccCode", ""))
        child_sgs = children_map.get(sg.id, [])
        child_nodes = [_build_node(c) for c in child_sgs]
        total = sum(a["net"] for a in direct_accounts) + sum(c["total"] for c in child_nodes)
        node = {
            "type": "subGroup",
            "subGroupId": sg.id,
            "subGroupCode": sg.fixed_code,
            "subGroupName": sg.sub_group_name,
            "level": sg.level,
            "children": child_nodes,
            "accounts": direct_accounts,
            "total": total,
        }
        return node

    return [_build_node(r) for r in roots]


def get_profit_loss(params):
    """
    P&L from actual posted income and expense transactions.
    Uses GroupMaster.head_under == 'Profit & Loss'.
    Returns a hierarchical tree: Group → SubGroup (nested) → CC accounts.
    """
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    # 1. Load all P&L groups
    pl_groups = GroupMaster.query.filter_by(head_under="Profit & Loss", status="Active").all()
    pl_group_ids = [g.id for g in pl_groups]
    pl_groups_map = {g.id: g for g in pl_groups}

    empty_resp = {"message": "OK", "data": {
        "income": [], "expense": [], "totalIncome": 0, "totalExpense": 0, "netProfit": 0,
        "fromDate": _fmt_date(from_date), "toDate": _fmt_date(to_date), "projectCode": project_code,
    }}, 200

    if not pl_group_ids:
        return empty_resp

    # 2. Eager-load all relevant CC codes in ONE query
    pl_ccs = CCCode.query.filter(
        or_(
            and_(CCCode.group_id.in_(pl_group_ids), CCCode.status == "Active"),
            and_(CCCode.pl_linked == True, CCCode.status == "Active"),
        )
    ).all()

    if not pl_ccs:
        return empty_resp

    cc_map = {cc.id: cc for cc in pl_ccs}
    all_pl_ids = list(cc_map.keys())

    # 3. Eager-load all SubGroupMasters that these CCs reference
    sg_ids = set()
    for cc in pl_ccs:
        if cc.pl_linked and cc.pl_sub_group_id:
            sg_ids.add(cc.pl_sub_group_id)
        elif cc.sub_group_id:
            sg_ids.add(cc.sub_group_id)
    # Also load parent chain
    all_sgs = SubGroupMaster.query.filter(SubGroupMaster.group_id.in_(pl_group_ids)).all() if pl_group_ids else []
    # Also load sub-groups for pl_linked groups that might be outside pl_group_ids
    pl_linked_group_ids = set()
    for cc in pl_ccs:
        if cc.pl_linked and cc.pl_group_id and cc.pl_group_id not in pl_group_ids:
            pl_linked_group_ids.add(cc.pl_group_id)
            grp = GroupMaster.query.get(cc.pl_group_id)
            if grp:
                pl_groups_map[grp.id] = grp
    if pl_linked_group_ids:
        all_sgs += SubGroupMaster.query.filter(SubGroupMaster.group_id.in_(list(pl_linked_group_ids))).all()
    all_subgroups_map = {sg.id: sg for sg in all_sgs}

    # 4. Single aggregated query for balances (excluding cancelled/reversed pairs)
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
        _not_cancelled(),
    )

    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.group_by(AccountingLedgerLine.cc_id)
    balances = {row[0]: (row[1], row[2]) for row in q.all()}

    # 5. Build tree: group_id → {sub_group_id → [accounts]}
    # Include ALL pl-linked CCs, even those with zero balances
    income_by_group = {}   # group_id → {sg_id → [rows]}
    expense_by_group = {}  # group_id → {sg_id → [rows]}
    total_income = Decimal("0")
    total_expense = Decimal("0")

    for cc in pl_ccs:
        dr_raw, cr_raw = balances.get(cc.id, (0, 0))
        dr_total = _d(dr_raw)
        cr_total = _d(cr_raw)
        net = cr_total - dr_total

        if cc.pl_linked and cc.pl_group_id:
            grp_id = cc.pl_group_id
            sg_id = cc.pl_sub_group_id
        else:
            grp_id = cc.group_id
            sg_id = cc.sub_group_id

        # Determine side by group membership, not by value sign
        grp = pl_groups_map.get(grp_id)
        is_income_group = grp and any(
            kw in (grp.group_name or "").lower() for kw in _PL_INCOME_KEYWORDS
        )

        row = {
            "type": "account",
            "ccId": cc.id,
            "ccCode": cc.cc_code,
            "ccName": cc.cc_name,
            "plLinked": bool(cc.pl_linked),
            "debit": float(dr_total),
            "credit": float(cr_total),
            "net": float(abs(net)),
        }

        if is_income_group:
            bucket = income_by_group
            total_income += net
        else:
            bucket = expense_by_group
            total_expense -= net

        bucket.setdefault(grp_id, {}).setdefault(sg_id, []).append(row)

    # 6. Assemble hierarchical response
    def _build_group_tree(group_bucket):
        result = []
        for grp_id, sg_accounts in sorted(group_bucket.items(), key=lambda x: (pl_groups_map.get(x[0], GroupMaster()).group_name or "")):
            grp = pl_groups_map.get(grp_id)
            grp_name = grp.group_name if grp else "Ungrouped"

            # Accounts without sub-group
            ungrouped = sorted(sg_accounts.pop(None, []), key=lambda a: a.get("ccCode", ""))

            # Build sub-group tree for this group's sub-groups
            sg_tree = _build_subgroup_tree(sg_accounts, all_subgroups_map) if sg_accounts else []

            group_total = (
                sum(a["net"] for a in ungrouped)
                + sum(n["total"] for n in sg_tree)
            )

            result.append({
                "groupId": grp_id,
                "groupName": grp_name,
                "subGroups": sg_tree,
                "accounts": ungrouped,
                "total": group_total,
            })
        return result

    income_tree = _build_group_tree(income_by_group)
    expense_tree = _build_group_tree(expense_by_group)

    net_profit = float(total_income - total_expense)

    return {
        "message": "OK",
        "data": {
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "income": income_tree,
            "expense": expense_tree,
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
    Returns hierarchical tree: Group → SubGroup (nested) → CC accounts,
    plus special sections for Vendors, Banks and P&L retained earnings.
    """
    as_of_date = _parse_date(params.get("as_of_date") or params.get("to_date"))
    from_date = _parse_date(params.get("from_date"))
    project_code = params.get("project_code")
    # 1. Load all BS groups and their sub-groups
    bs_groups = GroupMaster.query.filter_by(head_under="Balance Sheet", status="Active").all()
    bs_group_ids = [g.id for g in bs_groups]
    bs_groups_map = {g.id: g for g in bs_groups}

    # Every CC sits in a BS group (group_id). pl_linked CCs also appear
    # in P&L under their pl_group_id, but they still belong here under
    # their BS group. The P&L result is shown under Equity for reference
    # but NOT added to totals (the individual CC balances already capture
    # all income/expense, so the BS balances from account totals alone).
    bs_ccs = CCCode.query.filter(
        CCCode.group_id.in_(bs_group_ids),
        CCCode.status == "Active",
    ).all() if bs_group_ids else []
    cc_map = {cc.id: cc for cc in bs_ccs}

    # Eager-load all sub-groups for BS groups
    all_sgs = SubGroupMaster.query.filter(
        SubGroupMaster.group_id.in_(bs_group_ids)
    ).all() if bs_group_ids else []
    all_subgroups_map = {sg.id: sg for sg in all_sgs}

    # 2. Single aggregated query for CC balances (excluding cancelled/reversed pairs)
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
        _not_cancelled(),
    )
    if as_of_date:
        cc_q = cc_q.filter(AccountingLedger.posting_date <= as_of_date)
    if from_date:
        cc_q = cc_q.filter(AccountingLedger.posting_date >= from_date)
    if project_code:
        cc_q = cc_q.filter(AccountingLedger.project_code == project_code)
    cc_q = cc_q.group_by(AccountingLedgerLine.cc_id)

    # Date/project filter helper for vendor and bank queries
    def _apply_date_project_filters(q):
        if as_of_date:
            q = q.filter(AccountingLedger.posting_date <= as_of_date)
        if from_date:
            q = q.filter(AccountingLedger.posting_date >= from_date)
        if project_code:
            q = q.filter(AccountingLedger.project_code == project_code)
        return q

    # 5. Build CC code tree by group → sub-group
    asset_by_group = {}   # group_id → {sg_id → [rows]}
    liability_by_group = {}
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")

    cc_balances = {row[0]: (_d(row[1]), _d(row[2])) for row in cc_q.all()}

    def _is_asset_group(grp):
        if not grp:
            return True
        name = (grp.group_name or "").lower()
        return any(kw in name for kw in _BS_ASSET_KEYWORDS)

    # Place ALL BS CCs on their group's natural side (Tally standard)
    for cc in bs_ccs:
        dr_total, cr_total = cc_balances.get(cc.id, (Decimal("0"), Decimal("0")))
        net = dr_total - cr_total

        grp_id = cc.group_id
        sg_id = cc.sub_group_id
        grp = bs_groups_map.get(grp_id)
        is_asset = _is_asset_group(grp)

        # For assets: net = Dr - Cr (positive = natural debit balance)
        # For liabilities: net = Cr - Dr (positive = natural credit balance)
        # Negative net means balance is opposite to group's natural side
        side_net = net if is_asset else -net

        row = {
            "type": "account",
            "ccId": cc.id,
            "ccCode": cc.cc_code,
            "ccName": cc.cc_name,
            "debit": float(dr_total),
            "credit": float(cr_total),
            "net": float(side_net),
        }

        if is_asset:
            asset_by_group.setdefault(grp_id, {}).setdefault(sg_id, []).append(row)
            total_assets += net
        else:
            liability_by_group.setdefault(grp_id, {}).setdefault(sg_id, []).append(row)
            total_liabilities += -net  # Cr - Dr: positive when credit-heavy

    def _build_bs_group_tree(group_bucket):
        result = []
        for grp_id, sg_accounts in sorted(group_bucket.items(), key=lambda x: (bs_groups_map.get(x[0], GroupMaster()).group_name or "")):
            grp = bs_groups_map.get(grp_id)
            ungrouped = sorted(sg_accounts.pop(None, []), key=lambda a: a.get("ccCode", ""))
            sg_tree = _build_subgroup_tree(sg_accounts, all_subgroups_map) if sg_accounts else []
            group_total = sum(a["net"] for a in ungrouped) + sum(n["total"] for n in sg_tree)
            result.append({
                "groupId": grp_id,
                "groupName": grp.group_name if grp else "Ungrouped",
                "subGroups": sg_tree,
                "accounts": ungrouped,
                "total": group_total,
            })
        return result

    # Tree building deferred until after bank/cash accounts are placed into groups

    # 6. Vendors — creditors vs debtors
    sundry_creditors = Decimal("0")
    sundry_debtors = Decimal("0")
    creditor_details = []
    debtor_details = []

    vendor_q = _apply_date_project_filters(
        db.session.query(
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
            _not_cancelled(),
        )
    ).group_by(AccountingLedgerLine.vendor_id)

    vendor_rows = vendor_q.all()
    all_vids = {r[0] for r in vendor_rows if r[0]}
    vendor_cache = {}
    if all_vids:
        for v in Vendor.query.filter(Vendor.id.in_(list(all_vids))).all():
            vendor_cache[v.id] = v

    for vid, dr, cr in vendor_rows:
        if not vid:
            continue
        v = vendor_cache.get(vid)
        if not v:
            continue
        net = _d(dr) - _d(cr)
        if net == 0:
            continue
        row = {
            "type": "vendor",
            "id": v.id,
            "code": v.ledger_code,
            "name": v.ledger_name,
            "isDebtor": v.is_debtor,
            "balance": float(abs(net)),
        }
        if net < 0:
            sundry_creditors += abs(net)
            creditor_details.append(row)
        else:
            sundry_debtors += net
            debtor_details.append(row)

    vendor_assets = []
    vendor_liabilities = []

    if sundry_debtors > 0:
        debtor_details.sort(key=lambda r: r["balance"], reverse=True)
        vendor_assets.append({
            "type": "vendorSummary",
            "code": "SUNDRY_DEBTORS",
            "name": "Sundry Debtors",
            "balance": float(sundry_debtors),
            "details": debtor_details,
        })
        total_assets += sundry_debtors

    if sundry_creditors > 0:
        creditor_details.sort(key=lambda r: r["balance"], reverse=True)
        vendor_liabilities.append({
            "type": "vendorSummary",
            "code": "SUNDRY_CREDITORS",
            "name": "Sundry Creditors",
            "balance": float(sundry_creditors),
            "details": creditor_details,
        })
        total_liabilities += sundry_creditors

    # 7. Bank/Cash
    bank_assets = []
    bank_liabilities = []
    bank_total = Decimal("0")

    bank_q = _apply_date_project_filters(
        db.session.query(
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
            _not_cancelled(),
        )
    ).group_by(AccountingLedgerLine.bank_cash_id)

    bank_rows = bank_q.all()
    all_bc_ids = {r[0] for r in bank_rows if r[0]}
    bc_cache = {}
    if all_bc_ids:
        for bc in BankCash.query.filter(BankCash.id.in_(list(all_bc_ids))).all():
            bc_cache[bc.id] = bc

    for bc_id, dr, cr in bank_rows:
        if not bc_id:
            continue
        bc = bc_cache.get(bc_id)
        if not bc:
            continue
        net = _d(dr) - _d(cr)
        if net == 0:
            continue

        # If bank has a BS group assigned, place it in the group tree (like CC codes)
        if bc.group_id and bc.group_id in bs_groups_map:
            sg_id = bc.sub_group_id
            grp = bs_groups_map.get(bc.group_id)
            is_asset = _is_asset_group(grp)
            side_net = net if is_asset else -net

            tree_row = {
                "type": "account",
                "ccId": f"bank_{bc.id}",
                "ccCode": bc.bank_code,
                "ccName": bc.bank_name or bc.bank_holder_name or "",
                "debit": float(_d(dr)),
                "credit": float(_d(cr)),
                "net": float(side_net),
                "_bankCashId": bc.id,
            }

            if is_asset:
                asset_by_group.setdefault(bc.group_id, {}).setdefault(sg_id, []).append(tree_row)
                total_assets += net
            else:
                liability_by_group.setdefault(bc.group_id, {}).setdefault(sg_id, []).append(tree_row)
                total_liabilities += -net
            bank_total += net if net > 0 else Decimal("0")
            continue

        row = {
            "type": "bankCash",
            "id": bc.id,
            "code": bc.bank_code,
            "name": bc.bank_name or bc.bank_holder_name or "",
            "accountType": bc.type,
            "balance": float(abs(net)),
        }
        if net > 0:
            bank_assets.append(row)
            total_assets += net
            bank_total += net
        else:
            bank_liabilities.append(row)
            total_liabilities += abs(net)

    # Ensure ALL BS groups appear in the tree, even those with no CC codes
    for grp in bs_groups:
        is_asset = _is_asset_group(grp)
        if is_asset:
            asset_by_group.setdefault(grp.id, {})
        else:
            liability_by_group.setdefault(grp.id, {})

    # 8. P&L retained earnings — inject into Equity group tree
    pl_data, _ = get_profit_loss({
        "to_date": _fmt_date(as_of_date),
        "from_date": _fmt_date(from_date),
        "project_code": project_code,
    })
    net_profit = Decimal(str(pl_data["data"]["netProfit"]))

    equity_group_id = None
    pl_sg_id = None
    for grp in bs_groups:
        if "equity" in (grp.group_name or "").lower():
            equity_group_id = grp.id
            break
    if equity_group_id:
        for sg in all_sgs:
            if sg.group_id == equity_group_id:
                sg_name = (sg.sub_group_name or "").lower()
                if "current year" in sg_name or "current period" in sg_name:
                    pl_sg_id = sg.id
                    break
                elif ("profit" in sg_name and "loss" in sg_name) and not pl_sg_id:
                    pl_sg_id = sg.id

    # Place P&L result under Equity > Current Year Profit / Loss — FOR DISPLAY ONLY.
    # The individual income/expense CC balances already flow through their own BS
    # groups (pl_linked CCs still have a group_id pointing to a BS group), so the
    # net profit is already captured in total_assets/total_liabilities through the
    # CC account rows.  Adding net_profit to total_liabilities a second time would
    # make the BS grand total wrong.  The row is therefore _informational: True and
    # is NOT counted in any total — it shows management the period P&L contribution
    # in the Equity section without distorting the balance.
    pl_section = None
    if net_profit != 0 and equity_group_id and pl_sg_id:
        pl_row = {
            "type": "account",
            "ccId": "pl_result",
            "ccCode": "P&L",
            "ccName": "Net Profit (Current Period)" if net_profit > 0 else "Net Loss (Current Period)",
            "debit": 0.0,
            "credit": 0.0,
            "net": float(net_profit),
            "_informational": True,  # display only — not counted in group/section totals
        }
        liability_by_group.setdefault(equity_group_id, {}).setdefault(pl_sg_id, []).append(pl_row)
        # Do NOT add net_profit to total_liabilities — it is already in the CC account rows
    elif net_profit != 0:
        pl_section = {
            "type": "plResult",
            "code": "NET_PROFIT" if net_profit > 0 else "NET_LOSS",
            "name": "Net Profit (Current Period)" if net_profit > 0 else "Net Loss (Current Period)",
            "balance": float(abs(net_profit)),
        }

    # Build group trees now that all groups, bank/cash and P&L are in the buckets
    asset_groups = _build_bs_group_tree(asset_by_group)
    liability_groups = _build_bs_group_tree(liability_by_group)

    return {
        "message": "OK",
        "data": {
            "asOfDate": _fmt_date(as_of_date),
            "fromDate": _fmt_date(from_date),
            "projectCode": project_code,
            "assetGroups": asset_groups,
            "liabilityGroups": liability_groups,
            "vendorAssets": vendor_assets,
            "vendorLiabilities": vendor_liabilities,
            "bankAssets": bank_assets,
            "bankLiabilities": bank_liabilities,
            "bankTotal": float(bank_total),
            "plResult": pl_section,
            "totalAssets": float(total_assets),
            "totalLiabilities": float(total_liabilities),
            "difference": float(total_assets - total_liabilities),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# RECONCILIATION — drill-down into any account's transactions
# ═══════════════════════════════════════════════════════════════════════════

def get_reconciliation(params):
    """
    Returns all ledger transactions for a given account (CC, Vendor, BankCash)
    within a date range, grouped by source_type. Each transaction includes
    source details (voucher no, date, Dr/Cr, amount, narration, project code)
    and a link path to the source document.
    """
    account_type = params.get("account_type")
    account_id = params.get("account_id")
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    if not account_type or not account_id:
        return {"message": "account_type and account_id required", "data": []}, 400

    account_id = int(account_id)

    # Build query
    q = db.session.query(
        AccountingLedgerLine,
        AccountingLedger.posting_date,
        AccountingLedger.voucher_no,
        AccountingLedger.source_type,
        AccountingLedger.source_id,
        AccountingLedger.project_code,
        AccountingLedger.remarks,
        AccountingLedger.is_reversal,
        AccountingLedger.is_reversed,
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)

    if account_type == "CC":
        q = q.filter(AccountingLedgerLine.account_type == "CC", AccountingLedgerLine.cc_id == account_id)
    elif account_type == "Vendor":
        q = q.filter(AccountingLedgerLine.account_type == "Vendor", AccountingLedgerLine.vendor_id == account_id)
    elif account_type == "BankCash":
        q = q.filter(AccountingLedgerLine.account_type == "BankCash", AccountingLedgerLine.bank_cash_id == account_id)
    else:
        return {"message": f"Unknown account_type: {account_type}", "data": []}, 400

    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.order_by(AccountingLedger.posting_date, AccountingLedger.id, AccountingLedgerLine.sl_no)

    # Group by source type
    by_source = {}
    total_dr = Decimal("0")
    total_cr = Decimal("0")

    for line, post_date, voucher_no, src_type, src_id, proj, remark, is_rev, is_revd in q.all():
        dr = float(line.amount) if line.dr_cr == "Dr" else 0.0
        cr = float(line.amount) if line.dr_cr == "Cr" else 0.0
        total_dr += _d(dr)
        total_cr += _d(cr)

        link = _doc_link(src_type, src_id)
        # counted like every report (the pair nets to zero); the UI marks them
        is_cancelled, cancel_label = _cancel_flags(is_rev, is_revd)

        entry = {
            "date": _fmt_date(post_date),
            "voucherNo": voucher_no,
            "sourceId": src_id,
            "projectCode": proj,
            "narration": line.narration or remark or "",
            "drCr": line.dr_cr,
            "debit": dr,
            "credit": cr,
            "link": link,
            "isCancelled": is_cancelled,
            "cancelLabel": cancel_label,
        }

        label = SOURCE_TYPE_LABELS.get(src_type, src_type or "Other")
        by_source.setdefault(label, []).append(entry)

    account_name = _get_account_name(account_type, account_id)

    # Build grouped response
    groups = []
    for label, entries in by_source.items():
        grp_dr = sum(e["debit"] for e in entries)
        grp_cr = sum(e["credit"] for e in entries)
        groups.append({
            "sourceType": label,
            "entries": entries,
            "count": len(entries),
            "totalDebit": grp_dr,
            "totalCredit": grp_cr,
        })

    groups.sort(key=lambda g: g["totalDebit"] + g["totalCredit"], reverse=True)

    return {
        "message": "OK",
        "data": {
            "accountType": account_type,
            "accountId": account_id,
            "accountName": account_name,
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "totalDebit": float(total_dr),
            "totalCredit": float(total_cr),
            "net": float(total_dr - total_cr),
            "groups": groups,
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
    source_type = params.get("source_type")
    if source_type:
        q = q.filter(AccountingLedger.source_type == source_type)

    include_cancelled = _include_cancelled(params)
    cancelled_count = q.filter(_cancelled()).count()
    if not include_cancelled:
        q = q.filter(_not_cancelled())

    q = q.order_by(AccountingLedger.posting_date.desc(), AccountingLedger.id.desc())

    postings = q.all()

    # Bulk-load all lines' account names to avoid N+1
    all_lines = []
    for p in postings:
        all_lines.extend(p.lines)
    db_cc_ids = {l.cc_id for l in all_lines if l.account_type == "CC" and l.cc_id}
    db_vendor_ids = {l.vendor_id for l in all_lines if l.account_type == "Vendor" and l.vendor_id}
    db_bc_ids = {l.bank_cash_id for l in all_lines if l.account_type == "BankCash" and l.bank_cash_id}

    name_cache = {}
    if db_cc_ids:
        for cc in CCCode.query.filter(CCCode.id.in_(list(db_cc_ids))).all():
            name_cache[("CC", cc.id)] = f"{cc.cc_code} - {cc.cc_name}"
    if db_vendor_ids:
        for v in Vendor.query.filter(Vendor.id.in_(list(db_vendor_ids))).all():
            name_cache[("Vendor", v.id)] = f"{v.ledger_code} - {v.ledger_name}"
    if db_bc_ids:
        for bc in BankCash.query.filter(BankCash.id.in_(list(db_bc_ids))).all():
            name_cache[("BankCash", bc.id)] = f"{bc.bank_code} - {bc.bank_name or bc.bank_holder_name or ''}"

    entries = []
    for posting in postings:
        lines_data = []
        for line in posting.lines:
            acct_id = line.cc_id or line.vendor_id or line.bank_cash_id
            lines_data.append({
                "slNo": line.sl_no,
                "accountType": line.account_type,
                "accountName": name_cache.get((line.account_type, acct_id), str(acct_id)),
                "drCr": line.dr_cr,
                "amount": float(line.amount),
                "narration": line.narration,
            })

        is_cancelled, cancel_label = _cancel_flags(posting.is_reversal, posting.is_reversed)
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
            "isCancelled": is_cancelled,
            "cancelLabel": cancel_label,
            "lines": lines_data,
        })

    return {
        "message": "OK",
        "data": {
            "date": _fmt_date(target_date),
            "projectCode": project_code,
            "includeCancelled": include_cancelled,
            "cancelledCount": cancelled_count,
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
    include_cancelled = _include_cancelled(params)
    cancelled_count = q.filter(_cancelled()).count()
    if not include_cancelled:
        q = q.filter(_not_cancelled())
    q = q.order_by(AccountingLedger.posting_date, AccountingLedger.id)

    entries = []
    for posting in q.all():
        is_cancelled, cancel_label = _cancel_flags(posting.is_reversal, posting.is_reversed)
        entries.append({
            "isCancelled": is_cancelled,
            "cancelLabel": cancel_label,
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
            "includeCancelled": include_cancelled,
            "cancelledCount": cancelled_count,
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
        _not_cancelled(),
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
        _not_cancelled(),
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
        _not_cancelled(),
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


def get_gst_reconciliation(params):
    gst_type = params.get("gst_type")
    dr_cr = params.get("dr_cr")
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    if not gst_type and not dr_cr:
        return {"message": "gst_type or dr_cr required", "data": []}, 400

    q = db.session.query(
        AccountingLedgerLine,
        AccountingLedger.posting_date,
        AccountingLedger.voucher_no,
        AccountingLedger.source_type,
        AccountingLedger.source_id,
        AccountingLedger.project_code,
        AccountingLedger.remarks,
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).filter(AccountingLedgerLine.gst_type.isnot(None), _not_cancelled())

    if gst_type:
        q = q.filter(AccountingLedgerLine.gst_type == gst_type)

    if dr_cr:
        q = q.filter(AccountingLedgerLine.dr_cr == dr_cr)
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)

    q = q.order_by(AccountingLedger.posting_date, AccountingLedger.id, AccountingLedgerLine.sl_no)

    by_source = {}
    total_dr = Decimal("0")
    total_cr = Decimal("0")

    for line, post_date, voucher_no, src_type, src_id, proj, remark in q.all():
        dr = float(line.amount) if line.dr_cr == "Dr" else 0.0
        cr = float(line.amount) if line.dr_cr == "Cr" else 0.0
        total_dr += _d(dr)
        total_cr += _d(cr)

        link = _doc_link(src_type, src_id)

        entry = {
            "date": _fmt_date(post_date),
            "voucherNo": voucher_no,
            "sourceId": src_id,
            "projectCode": proj,
            "narration": line.narration or remark or "",
            "drCr": line.dr_cr,
            "debit": dr,
            "credit": cr,
            "link": link,
        }

        label = SOURCE_TYPE_LABELS.get(src_type, src_type or "Other")
        by_source.setdefault(label, []).append(entry)

    groups = []
    for label, entries in by_source.items():
        grp_dr = sum(e["debit"] for e in entries)
        grp_cr = sum(e["credit"] for e in entries)
        groups.append({
            "sourceType": label,
            "entries": entries,
            "count": len(entries),
            "totalDebit": grp_dr,
            "totalCredit": grp_cr,
        })

    groups.sort(key=lambda g: g["totalDebit"] + g["totalCredit"], reverse=True)

    side_label = "Input" if dr_cr == "Dr" else "Output" if dr_cr == "Cr" else "All"
    type_label = gst_type or "All Types"

    return {
        "message": "OK",
        "data": {
            "accountType": "GST",
            "accountId": gst_type or "all",
            "accountName": f"{type_label} — {side_label} GST",
            "fromDate": _fmt_date(from_date),
            "toDate": _fmt_date(to_date),
            "projectCode": project_code,
            "totalDebit": float(total_dr),
            "totalCredit": float(total_cr),
            "net": float(total_dr - total_cr),
            "groups": groups,
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# PROJECT FINANCIAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def get_project_summary(params):
    project_code = params.get("project_code")
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))

    base_filter = []
    if project_code:
        base_filter.append(AccountingLedger.project_code == project_code)
    if from_date:
        base_filter.append(AccountingLedger.posting_date >= from_date)
    if to_date:
        base_filter.append(AccountingLedger.posting_date <= to_date)

    # CC and BankCash: simple group by account_type + dr_cr
    q = db.session.query(
        AccountingLedgerLine.account_type,
        AccountingLedgerLine.dr_cr,
        func.sum(AccountingLedgerLine.amount).label("total"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).filter(AccountingLedgerLine.account_type.in_(["CC", "BankCash"]), _not_cancelled(), *base_filter
    ).group_by(AccountingLedgerLine.account_type, AccountingLedgerLine.dr_cr)

    summary = {}
    for acct_type, dr_cr, total in q.all():
        summary[f"{acct_type}_{dr_cr}"] = float(total or 0)

    # Vendor lines: split by is_debtor (sundry debtors vs sundry creditors)
    vq = db.session.query(
        func.coalesce(Vendor.is_debtor, False).label("is_debtor"),
        AccountingLedgerLine.dr_cr,
        func.sum(AccountingLedgerLine.amount).label("total"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).outerjoin(Vendor, AccountingLedgerLine.vendor_id == Vendor.id
    ).filter(AccountingLedgerLine.account_type == "Vendor", _not_cancelled(), *base_filter
    ).group_by("is_debtor", AccountingLedgerLine.dr_cr)

    for is_debtor, dr_cr, total in vq.all():
        prefix = "debtor" if is_debtor else "creditor"
        summary[f"{prefix}_{dr_cr}"] = float(total or 0)

    return {
        "message": "OK",
        "data": {
            "projectCode": project_code,
            "ccDebit": summary.get("CC_Dr", 0),
            "ccCredit": summary.get("CC_Cr", 0),
            "creditorDebit": summary.get("creditor_Dr", 0),
            "creditorCredit": summary.get("creditor_Cr", 0),
            "debtorDebit": summary.get("debtor_Dr", 0),
            "debtorCredit": summary.get("debtor_Cr", 0),
            "bankDebit": summary.get("BankCash_Dr", 0),
            "bankCredit": summary.get("BankCash_Cr", 0),
            # backward compat: total vendor = creditor + debtor
            "vendorDebit": summary.get("creditor_Dr", 0) + summary.get("debtor_Dr", 0),
            "vendorCredit": summary.get("creditor_Cr", 0) + summary.get("debtor_Cr", 0),
        },
    }, 200


# ═══════════════════════════════════════════════════════════════════════════
# GROUP-WISE LEDGER
# ═══════════════════════════════════════════════════════════════════════════

def get_group_ledger(params):
    """
    Tally-style Group Summary.
    Shows ALL groups from GroupMaster (even zero-balance) with Dr/Cr totals
    aggregated from CC, Vendor and BankCash account lines.
    """
    from_date = _parse_date(params.get("from_date"))
    to_date = _parse_date(params.get("to_date"))
    project_code = params.get("project_code")

    date_filters = []
    if from_date:
        date_filters.append(AccountingLedger.posting_date >= from_date)
    if to_date:
        date_filters.append(AccountingLedger.posting_date <= to_date)
    if project_code:
        date_filters.append(AccountingLedger.project_code == project_code)

    # Start with ALL active groups — Tally shows every group
    all_groups = GroupMaster.query.filter(
        GroupMaster.status != "Deleted",
    ).order_by(GroupMaster.group_name).all()

    group_totals = {}
    for g in all_groups:
        group_totals[g.id] = {"dr": Decimal("0"), "cr": Decimal("0")}

    _dr_sum = func.coalesce(func.sum(case(
        (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
        else_=literal_column("0"),
    )), 0)
    _cr_sum = func.coalesce(func.sum(case(
        (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
        else_=literal_column("0"),
    )), 0)

    # --- 1) CC accounts: aggregate per cc_id, then map to groups ---
    # CC codes have group_id (BS group) and optionally pl_group_id (P&L group
    # when pl_linked=True).  Each CC's totals go under its native group_id,
    # AND also under pl_group_id when pl_linked is set.
    cc_balances = db.session.query(
        AccountingLedgerLine.cc_id, _dr_sum.label("dr"), _cr_sum.label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).filter(AccountingLedgerLine.account_type == "CC", _not_cancelled(), *date_filters
    ).group_by(AccountingLedgerLine.cc_id).all()

    if cc_balances:
        cc_obj_ids = [row[0] for row in cc_balances]
        cc_objs = CCCode.query.filter(CCCode.id.in_(cc_obj_ids)).all()
        cc_map = {cc.id: cc for cc in cc_objs}

        for cc_id, dr, cr in cc_balances:
            cc = cc_map.get(cc_id)
            if not cc:
                continue
            dr_val = _d(dr)
            cr_val = _d(cr)
            # pl_linked overrides: use pl_group_id instead of group_id
            if cc.pl_linked and cc.pl_group_id:
                gid = cc.pl_group_id
            else:
                gid = cc.group_id
            if gid:
                t = group_totals.setdefault(gid, {"dr": Decimal("0"), "cr": Decimal("0")})
                t["dr"] += dr_val
                t["cr"] += cr_val

    # --- 2) BankCash accounts: group via BankCash.group_id ---
    bank_q = db.session.query(
        BankCash.group_id, _dr_sum.label("dr"), _cr_sum.label("cr"),
    ).join(AccountingLedgerLine, AccountingLedgerLine.bank_cash_id == BankCash.id
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).filter(AccountingLedgerLine.account_type == "BankCash", _not_cancelled(), *date_filters
    ).group_by(BankCash.group_id)

    for gid, dr, cr in bank_q.all():
        if gid is None:
            continue
        t = group_totals.setdefault(gid, {"dr": Decimal("0"), "cr": Decimal("0")})
        t["dr"] += _d(dr)
        t["cr"] += _d(cr)

    # --- 3) Vendor accounts: use is_debtor flag directly ---
    # Vendors don't have group_id; is_debtor determines Creditor vs Debtor
    vendor_q = db.session.query(
        func.coalesce(Vendor.is_debtor, False).label("is_debtor"),
        _dr_sum.label("dr"), _cr_sum.label("cr"),
    ).join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id
    ).outerjoin(Vendor, AccountingLedgerLine.vendor_id == Vendor.id
    ).filter(AccountingLedgerLine.account_type == "Vendor", _not_cancelled(), *date_filters
    ).group_by("is_debtor")

    vendor_rows = {}  # "creditor"/"debtor" -> {dr, cr}
    for is_debtor, dr, cr in vendor_q.all():
        key = "debtor" if is_debtor else "creditor"
        vendor_rows[key] = {"dr": _d(dr), "cr": _d(cr)}

    # --- Build result rows ---
    rows = []
    group_map = {g.id: g for g in all_groups}

    for gid, totals in group_totals.items():
        dr = totals["dr"]
        cr = totals["cr"]
        net = float(dr - cr)
        grp = group_map.get(gid)
        rows.append({
            "groupId": gid,
            "groupName": grp.group_name if grp else "Ungrouped",
            "headUnder": grp.head_under if grp else None,
            "debit": float(dr),
            "credit": float(cr),
            "net": net,
        })

    # Vendor rows always appear as dedicated Balance Sheet entries
    for key, label, group_key in [("creditor", "Sundry Creditors", "SUNDRY_CREDITORS"),
                                  ("debtor", "Sundry Debtors", "SUNDRY_DEBTORS")]:
        totals = vendor_rows.get(key, {"dr": Decimal("0"), "cr": Decimal("0")})
        dr = totals["dr"]
        cr = totals["cr"]
        rows.append({
            "groupId": None,
            "groupKey": group_key,  # breakdown API key for these vendor rows
            "groupName": label,
            "headUnder": "Balance Sheet",
            "debit": float(dr),
            "credit": float(cr),
            "net": float(dr - cr),
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
