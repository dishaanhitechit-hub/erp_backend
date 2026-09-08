from datetime import datetime
from app.extensions import db
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode
from app.response import res


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# All 50 codes in display order — only leaf codes, no section headers
_ALL_CODES = [
    "CRIN", "CRHL", "CRAP", "UCAP", "WIPS", "INOC",
    "DRCW", "DRMC", "DRFD", "DRMH", "DRUS", "DRMR", "DRLC", "DRLS", "DRMS",
    "IRDC", "IRAD", "IRLE", "IRFS", "IRMR", "IRLU", "IRMT", "IRPS", "IRSD",
    "IRIM", "IRIL", "IRFM", "IRTT", "IRLH", "IRLM", "IRLT",
    "IOFM", "IOHR", "IOME", "IOMS", "IOMB", "IOSS", "IOVR", "IOTV",
    "IOCR", "CRBC", "CRBD", "CRCC", "CRDR", "CRES", "CRIC", "CRIP", "CRLC", "CRPF", "CRIT",
]

_SALE_CODES = {"CRIN", "CRHL", "CRAP", "UCAP", "WIPS", "INOC"}


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

        # ── Build rows — one per code, workDone/booked/stock/actual = null (future) ──
        rows = []
        for code in _ALL_CODES:
            if code in _SALE_CODES:
                # Order column: total sale value under CRIN only; rest null for now
                order_val = sale_order_value if code == "CRIN" else None
            else:
                val = cc_map.get(code)
                order_val = val if val is not None else None

            rows.append({
                "code":     code,
                "order":    order_val,
                "workDone": None,
                "booked":   None,
                "stock":    None,
                "actual":   None,
            })

        return res("Profit & Loss fetched", {"rows": rows}, 200)

    except Exception as e:
        return res(str(e), [], 500)
