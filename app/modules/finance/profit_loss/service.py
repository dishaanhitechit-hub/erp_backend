from datetime import datetime
from app.extensions import db
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode

# DE sibling codes stored per-item — DRCW is their computed sum, not stored
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

        # DRCW is no longer stored as its own BudgetItemCCCode row —
        # derive it as the sum of all stored DE sibling codes.
        cc_map["DRCW"] = sum(cc_map.get(c, 0) for c in _DE_SIBLING_CODES)

        # ── B2. Overhead CC codes — estimated costs from BudgetMaster.overhead_data ──
        # These live in a JSON column; aggregate in Python after fetching matching budgets.
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
                "workDone": None,
                "booked":   booked_val,
                "stock":    None,
                "actual":   None,
            })

        return res("Profit & Loss fetched", {"rows": rows}, 200)

    except Exception as e:
        return res(str(e), [], 500)
