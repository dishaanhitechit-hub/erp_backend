from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, case, literal_column

from app.extensions import db
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode
from app.models.accounting import AccountingLedger, AccountingLedgerLine
from app.models.cc_code import CCCode

_DE_SIBLING_CODES = {"DRMC", "DRFD", "DRMH", "DRUS", "DRMR", "DRLC", "DRLS", "DRMS"}
from app.models.purchaseBill import PurchaseBillMaster, PurchaseBillItem
from app.response import res


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


_ALL_CODES = [
    "CRIN", "CRHL", "CRAP", "UCAP", "WIPS", "INOC",
    "DRCW", "DRMC", "DRFD", "DRMH", "DRUS", "DRMR", "DRLC", "DRLS", "DRMS",
    "IRDC", "IRAD", "IRLE", "IRFS", "IRMR", "IRLU", "IRMT", "IRPS", "IRSD",
    "IRIM", "IRIL", "IRFM", "IRTT", "IRLH", "IRLM", "IRLT",
    "IOFM", "IOHR", "IOME", "IOMS", "IOMB", "IOSS", "IOVR", "IOTV",
    "IOCR", "CRBC", "CRBD", "CRCC", "CRDR", "CRES", "CRIC", "CRIP", "CRLC", "CRPF", "CRIT",
]

_SALE_CODES = {"CRIN", "CRHL", "CRAP", "UCAP", "WIPS", "INOC"}

_STOCK_CODES = {"CARM", "DRMC", "DRFD", "DRMH", "DRUS", "DRMR", "DRLC", "DRLS", "DRMS"}


def _actual_from_ledger(project_code=None, from_date=None, to_date=None):
    """
    Actual column: net posted amounts per CC code from the accounting ledger.
    For expense codes: sum of Dr amounts (actual cost incurred).
    For revenue codes: sum of Cr amounts (actual revenue recognised).
    Returns {cc_code_upper: float}.
    """
    q = (
        db.session.query(
            func.upper(CCCode.cc_code).label("code"),
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("dr"),
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("cr"),
        )
        .join(CCCode, AccountingLedgerLine.cc_id == CCCode.id)
        .join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
        .filter(AccountingLedgerLine.account_type == "CC")
        .group_by(func.upper(CCCode.cc_code))
    )
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)

    result = {}
    for row in q.all():
        code = row.code
        dr_val = float(row.dr or 0)
        cr_val = float(row.cr or 0)
        if code in _SALE_CODES:
            result[code] = cr_val
        else:
            result[code] = dr_val
    return result


def _work_done_from_ledger(project_code=None, from_date=None, to_date=None):
    """
    Work Done column: same as actual for most codes (posted amounts).
    For sale-side codes:
      CRIN = actual invoiced revenue (Cr from sale_bill postings)
      CRHL = certified amounts on hold (from JE postings to CAHL)
      CRAP = certified amendment pending (from JE postings to CAAP)
      UCAP = work done uncertified (from JE postings to CAUM)
    """
    return _actual_from_ledger(project_code, from_date, to_date)


def _stock_from_ledger(project_code=None, from_date=None, to_date=None):
    """
    Stock column: net stock value per CC code.
    For CARM and DE-sibling codes that have inventory impact:
      Dr (stock received) - Cr (stock consumed) = closing stock value.
    Uses accounting ledger Dr-Cr for CARM-related codes.
    """
    q = (
        db.session.query(
            func.upper(CCCode.cc_code).label("code"),
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Dr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("dr"),
            func.coalesce(func.sum(case(
                (AccountingLedgerLine.dr_cr == "Cr", AccountingLedgerLine.amount),
                else_=literal_column("0"),
            )), 0).label("cr"),
        )
        .join(CCCode, AccountingLedgerLine.cc_id == CCCode.id)
        .join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
        .filter(
            AccountingLedgerLine.account_type == "CC",
            func.upper(CCCode.cc_code).in_([c.upper() for c in _STOCK_CODES]),
        )
        .group_by(func.upper(CCCode.cc_code))
    )
    if project_code:
        q = q.filter(AccountingLedger.project_code == project_code)
    if from_date:
        q = q.filter(AccountingLedger.posting_date >= from_date)
    if to_date:
        q = q.filter(AccountingLedger.posting_date <= to_date)

    result = {}
    for row in q.all():
        net = float(row.dr or 0) - float(row.cr or 0)
        if net != 0:
            result[row.code] = net
    return result


def get_pl_report(args):
    try:
        project_code = args.get("projectCode")
        from_date    = _parse_date(args.get("fromDate"))
        to_date      = _parse_date(args.get("toDate"))

        # ── A. SALE — total approved sale order amount → placed under CRIN ──
        so_query = OgSaleOrderMaster.query.filter(
            OgSaleOrderMaster.workflow_status == "Approved",
            OgSaleOrderMaster.status          == "Active",
        )
        if project_code:
            so_query = so_query.filter(OgSaleOrderMaster.project_code == project_code)
        if from_date:
            so_query = so_query.filter(OgSaleOrderMaster.og_sale_order_date >= from_date)
        if to_date:
            so_query = so_query.filter(OgSaleOrderMaster.og_sale_order_date <= to_date)

        sale_total = so_query.with_entities(
            db.func.coalesce(db.func.sum(OgSaleOrderMaster.total_amount), 0)
        ).scalar()
        sale_order_value = float(sale_total or 0)

        # ── B. EXPENSES — sum cc_total grouped by cc_code from approved budgets ──
        cc_query = (
            db.session.query(
                BudgetItemCCCode.cc_code,
                db.func.sum(BudgetItemCCCode.cc_total).label("total"),
            )
            .join(BudgetItem,   BudgetItemCCCode.budget_item_id == BudgetItem.id)
            .join(BudgetMaster, BudgetItem.budget_id            == BudgetMaster.id)
            .filter(
                BudgetMaster.workflow_status == "Approved",
                BudgetMaster.status          == "Active",
            )
        )
        if project_code:
            cc_query = cc_query.filter(BudgetMaster.project_code == project_code)
        if from_date:
            cc_query = cc_query.filter(BudgetMaster.budget_date >= from_date)
        if to_date:
            cc_query = cc_query.filter(BudgetMaster.budget_date <= to_date)

        cc_rows = cc_query.group_by(BudgetItemCCCode.cc_code).all()
        cc_map  = {row.cc_code.strip().upper(): float(row.total or 0) for row in cc_rows}

        cc_map["DRCW"] = sum(cc_map.get(c, 0) for c in _DE_SIBLING_CODES)

        # ── B2. Overhead CC codes — estimated costs from BudgetMaster.overhead_data ──
        bm_filter = BudgetMaster.query.filter(
            BudgetMaster.workflow_status == "Approved",
            BudgetMaster.status          == "Active",
        )
        if project_code:
            bm_filter = bm_filter.filter(BudgetMaster.project_code == project_code)
        if from_date:
            bm_filter = bm_filter.filter(BudgetMaster.budget_date >= from_date)
        if to_date:
            bm_filter = bm_filter.filter(BudgetMaster.budget_date <= to_date)

        for bm in bm_filter.with_entities(BudgetMaster.overhead_data).all():
            od = bm.overhead_data or {}
            for entry in od.get("projectOverhead", []) + od.get("employeeOverhead", []):
                code = (entry.get("ccCode") or "").strip().upper()
                if code:
                    cc_map[code] = cc_map.get(code, 0) + float(entry.get("estimatedCost") or 0)

        # ── C. BOOKED — approved Purchase Bill items grouped by cc_code ──
        pb_query = (
            db.session.query(
                PurchaseBillItem.cc_code,
                db.func.sum(PurchaseBillItem.basic_amount).label("total"),
            )
            .join(PurchaseBillMaster, PurchaseBillItem.purchase_bill_id == PurchaseBillMaster.id)
            .filter(PurchaseBillMaster.workflow_status == "Approved")
        )
        if project_code:
            pb_query = pb_query.filter(PurchaseBillMaster.project_code == project_code)
        if from_date:
            pb_query = pb_query.filter(PurchaseBillMaster.processing_date >= from_date)
        if to_date:
            pb_query = pb_query.filter(PurchaseBillMaster.processing_date <= to_date)

        pb_rows   = pb_query.group_by(PurchaseBillItem.cc_code).all()
        booked_map = {
            row.cc_code.strip().upper(): float(row.total or 0)
            for row in pb_rows
            if row.cc_code
        }

        # ── D. ACTUAL — posted amounts from accounting ledger ──
        actual_map = _actual_from_ledger(project_code, from_date, to_date)

        # ── E. WORK DONE — posted amounts (same source as actual) ──
        work_done_map = _work_done_from_ledger(project_code, from_date, to_date)

        # ── F. STOCK — closing stock values from accounting ledger ──
        stock_map = _stock_from_ledger(project_code, from_date, to_date)

        # Derive DRCW actual/workDone/stock as sum of DE siblings
        actual_map["DRCW"] = sum(actual_map.get(c, 0) for c in _DE_SIBLING_CODES)
        work_done_map["DRCW"] = sum(work_done_map.get(c, 0) for c in _DE_SIBLING_CODES)
        stock_map["DRCW"] = sum(stock_map.get(c, 0) for c in _DE_SIBLING_CODES)

        # ── Build rows ──
        rows = []
        for code in _ALL_CODES:
            if code in _SALE_CODES:
                order_val  = sale_order_value if code == "CRIN" else None
                booked_val = None
            else:
                order_val  = cc_map.get(code)
                booked_val = booked_map.get(code)

            rows.append({
                "code":     code,
                "order":    order_val,
                "workDone": work_done_map.get(code),
                "booked":   booked_val,
                "stock":    stock_map.get(code),
                "actual":   actual_map.get(code),
            })

        return res("Profit & Loss fetched", {"rows": rows}, 200)

    except Exception as e:
        return res(str(e), [], 500)
