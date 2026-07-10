from collections import defaultdict
from sqlalchemy import func
from app.extensions import db

from app.models.grnMaster import GrnMaster, GrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.models.orderMaster import OrderItem
from app.models.item import Item
from app.models.cc_code import CCCode
from app.response import res


def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════
# STOCK LIST  —  grouped by CC Code
# ══════════════════════════════════════════════════════════════════

def get_stock_list(project_code, item_category=None, page=1, limit=10):

    # ── received from GRN ────────────────────────────────────────
    grn_q = (
        db.session.query(
            OrderItem.item_code.label("item_code"),
            func.coalesce(func.sum(GrnItem.current_received_qty), 0).label("total_received_qty"),
            func.coalesce(
                func.sum(GrnItem.current_received_qty * OrderItem.rate), 0
            ).label("total_received_amount"),
        )
        .join(GrnMaster, GrnMaster.id == GrnItem.grn_id)
        .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
        .filter(
            GrnMaster.project_code == project_code,
            GrnMaster.workflow_status == "Approved",
        )
    )
    if item_category:
        grn_q = grn_q.filter(GrnMaster.item_category == item_category)

    grn_rows = grn_q.group_by(OrderItem.item_code).all()

    if not grn_rows:
        return res("Stock list fetched", [], 200)

    item_codes = [r.item_code for r in grn_rows if r.item_code]

    # ── issued from GIN ──────────────────────────────────────────
    gin_q = (
        db.session.query(
            OrderItem.item_code.label("item_code"),
            func.coalesce(func.sum(GinItem.issue_qty), 0).label("total_issued_qty"),
            func.coalesce(
                func.sum(GinItem.issue_qty * OrderItem.rate), 0
            ).label("total_issued_amount"),
        )
        .join(GinMaster, GinMaster.id == GinItem.gin_id)
        .join(OrderItem, OrderItem.id == GinItem.order_item_id)
        .filter(
            GinMaster.project_code == project_code,
            GinMaster.workflow_status == "Approved",
            OrderItem.item_code.in_(item_codes),
        )
    )
    if item_category:
        gin_q = gin_q.filter(GinMaster.item_category == item_category)

    gin_map = {r.item_code: r for r in gin_q.group_by(OrderItem.item_code).all()}

    # ── item master ──────────────────────────────────────────────
    item_map = {
        i.item_code: i
        for i in db.session.query(Item).filter(Item.item_code.in_(item_codes)).all()
    }

    # ── CC code map ──────────────────────────────────────────────
    cc_ids = [item_map[c].cc_code_id for c in item_codes if c in item_map]
    cc_map = {
        cc.id: cc
        for cc in db.session.query(CCCode).filter(CCCode.id.in_(cc_ids)).all()
    }

    # ── group by CC code ─────────────────────────────────────────
    groups = defaultdict(lambda: {"items": [], "totalStockAmount": 0.0})

    for row in grn_rows:
        code = row.item_code
        item = item_map.get(code)
        gin  = gin_map.get(code)

        receivedQty = float(row.total_received_qty)
        receivedAmt = float(row.total_received_amount)
        issuedQty   = float(gin.total_issued_qty) if gin else 0.0
        issuedAmt   = float(gin.total_issued_amount) if gin else 0.0

        stockQty    = receivedQty - issuedQty
        stockAmount = round(receivedAmt - issuedAmt, 2)

        cc_id     = item.cc_code_id if item else None
        cc        = cc_map.get(cc_id) if cc_id else None
        group_key = cc_id or "__none__"

        groups[group_key]["ccCode"] = cc.cc_code if cc else None
        groups[group_key]["ccName"] = cc.cc_name if cc else None
        groups[group_key]["totalStockAmount"] = round(
            groups[group_key]["totalStockAmount"] + stockAmount, 2
        )
        groups[group_key]["items"].append({
            "itemCode":    code,
            "itemName":    item.item_name if item else None,
            "unit":        item.unit.unit_name if item and item.unit else None,
            "receivedQty": receivedQty,
            "issuedQty":   issuedQty,
            "stockQty":    stockQty,
            "stockAmount": stockAmount,
        })

    # ── build full list with slNo ────────────────────────────────
    all_groups = []
    for group_sl, group_data in enumerate(groups.values(), start=1):
        all_groups.append({
            "slNo":             group_sl,
            "ccCode":           group_data["ccCode"],
            "ccName":           group_data["ccName"],
            "totalStockAmount": group_data["totalStockAmount"],
            "items": [
                {"slNo": f"{group_sl}.{i}", **item_row}
                for i, item_row in enumerate(group_data["items"], start=1)
            ],
        })

    # ── paginate on CC code groups ───────────────────────────────
    total_groups = len(all_groups)
    total_pages  = max(1, -(-total_groups // limit))   # ceiling division
    page         = max(1, min(page, total_pages))
    start        = (page - 1) * limit
    paged        = all_groups[start: start + limit]

    return res("Stock list fetched", {
        "pagination": {
            "currentPage": page,
            "totalPages":  total_pages,
            "totalGroups": total_groups,
            "limit":       limit,
        },
        "data": paged,
    }, 200)


# ══════════════════════════════════════════════════════════════════
# STOCK ITEM DETAIL  —  GRN & GIN breakdown, with search + date range
# ══════════════════════════════════════════════════════════════════

def _paginate(entries, page, limit):
    total      = len(entries)
    total_pages = max(1, -(-total // limit))
    page       = max(1, min(page, total_pages))
    start      = (page - 1) * limit
    return {
        "currentPage": page,
        "totalPages":  total_pages,
        "total":       total,
        "limit":       limit,
        "entries":     entries[start: start + limit],
    }


def _build_item_detail(project_code, item_code, from_date=None, to_date=None,
                       grn_page=1, gin_page=1, entries_limit=10):

    # ── GRN entries ──────────────────────────────────────────────
    grn_q = (
        db.session.query(
            GrnMaster.grn_no,
            GrnMaster.grn_date,
            GrnItem.current_received_qty,
            GrnItem.store_location,
            OrderItem.rate,
        )
        .join(GrnItem, GrnItem.grn_id == GrnMaster.id)
        .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
        .filter(
            GrnMaster.project_code == project_code,
            GrnMaster.workflow_status == "Approved",
            OrderItem.item_code == item_code,
        )
    )
    if from_date:
        grn_q = grn_q.filter(GrnMaster.grn_date >= from_date)
    if to_date:
        grn_q = grn_q.filter(GrnMaster.grn_date <= to_date)

    grn_entries         = []
    total_received_qty  = 0.0
    total_received_amt  = 0.0
    for r in grn_q.order_by(GrnMaster.grn_date).all():
        qty    = float(r.current_received_qty or 0)
        rate   = float(r.rate or 0)
        amount = round(qty * rate, 2)
        total_received_qty += qty
        total_received_amt += amount
        grn_entries.append({
            "grnNo":         r.grn_no,
            "grnDate":       _fmt_date(r.grn_date),
            "receivedQty":   qty,
            "rate":          rate,
            "amount":        amount,
            "storeLocation": r.store_location,
        })

    # ── GIN entries ──────────────────────────────────────────────
    gin_q = (
        db.session.query(
            GinMaster.gin_no,
            GinMaster.gin_date,
            GinItem.issue_qty,
            GinItem.item_used_location,
            OrderItem.rate,
        )
        .join(GinItem, GinItem.gin_id == GinMaster.id)
        .join(OrderItem, OrderItem.id == GinItem.order_item_id)
        .filter(
            GinMaster.project_code == project_code,
            GinMaster.workflow_status == "Approved",
            OrderItem.item_code == item_code,
            GinItem.order_item_id.isnot(None),
        )
    )
    if from_date:
        gin_q = gin_q.filter(GinMaster.gin_date >= from_date)
    if to_date:
        gin_q = gin_q.filter(GinMaster.gin_date <= to_date)

    gin_entries        = []
    total_issued_qty   = 0.0
    total_issued_amt   = 0.0
    for r in gin_q.order_by(GinMaster.gin_date).all():
        qty    = float(r.issue_qty or 0)
        rate   = float(r.rate or 0)
        amount = round(qty * rate, 2)
        total_issued_qty += qty
        total_issued_amt += amount
        gin_entries.append({
            "ginNo":       r.gin_no,
            "ginDate":     _fmt_date(r.gin_date),
            "issuedQty":   qty,
            "rate":        rate,
            "amount":      amount,
            "useLocation": r.item_used_location,
        })

    # ── item master ──────────────────────────────────────────────
    item = db.session.query(Item).filter(Item.item_code == item_code).first()

    return {
        "summary": {
            "itemCode":            item_code,
            "itemName":            item.item_name if item else None,
            "unit":                item.unit.unit_name if item and item.unit else None,
            "totalReceivedQty":    round(total_received_qty, 2),
            "totalReceivedAmount": round(total_received_amt, 2),
            "totalIssuedQty":      round(total_issued_qty, 2),
            "totalIssuedAmount":   round(total_issued_amt, 2),
            "stockQty":            round(total_received_qty - total_issued_qty, 2),
            "stockAmount":         round(total_received_amt - total_issued_amt, 2),
        },
        "grnEntries": _paginate(grn_entries, grn_page, entries_limit),
        "ginEntries": _paginate(gin_entries, gin_page, entries_limit),
    }


def get_stock_item_detail(project_code, item_code=None, search=None,
                          from_date=None, to_date=None,
                          grn_page=1, gin_page=1, entries_limit=10):

    if search:
        keyword       = f"%{search}%"
        matched_items = (
            db.session.query(Item)
            .filter(
                db.or_(
                    Item.item_code.ilike(keyword),
                    Item.item_name.ilike(keyword),
                )
            )
            .all()
        )
        if not matched_items:
            return res("No items found matching search", [], 200)

        result = [
            _build_item_detail(project_code, i.item_code, from_date, to_date,
                               grn_page, gin_page, entries_limit)
            for i in matched_items
        ]
        return res("Stock item detail fetched", result, 200)

    if item_code:
        detail = _build_item_detail(project_code, item_code, from_date, to_date,
                                    grn_page, gin_page, entries_limit)
        return res("Stock item detail fetched", detail, 200)

    return res("itemCode or search is required", [], 400)
