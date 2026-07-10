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
# STOCK LIST  —  one row per item
# ══════════════════════════════════════════════════════════════════

def get_stock_list(project_code, item_category=None):
    """
    Returns aggregated stock for every item that has at least one
    Final-Approved GRN in the given project.
    """

    # ── received quantities & amounts from GRN ──────────────────
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

    # ── issued quantities & amounts from GIN ────────────────────
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

    # ── item master details ──────────────────────────────────────
    items = (
        db.session.query(Item)
        .filter(Item.item_code.in_(item_codes))
        .all()
    )
    item_map = {i.item_code: i for i in items}

    # ── build flat rows then group by CC code ────────────────────
    # collect cc_code_id → CCCode mapping for all items
    cc_ids = [item_map[c].cc_code_id for c in item_codes if c in item_map]
    cc_objs = db.session.query(CCCode).filter(CCCode.id.in_(cc_ids)).all()
    cc_map = {cc.id: cc for cc in cc_objs}

    # group items under their CC code
    groups = defaultdict(lambda: {"items": [], "total_stock_amount": 0.0})

    for row in grn_rows:
        code = row.item_code
        item = item_map.get(code)
        gin = gin_map.get(code)

        received_qty = float(row.total_received_qty)
        received_amt = float(row.total_received_amount)
        issued_qty = float(gin.total_issued_qty) if gin else 0.0
        issued_amt = float(gin.total_issued_amount) if gin else 0.0

        stock_qty = received_qty - issued_qty
        stock_amount = round(received_amt - issued_amt, 2)

        cc_id = item.cc_code_id if item else None
        cc = cc_map.get(cc_id) if cc_id else None
        group_key = cc_id or "__none__"

        groups[group_key]["cc_code"] = cc.cc_code if cc else None
        groups[group_key]["cc_name"] = cc.cc_name if cc else None
        groups[group_key]["cc_id"] = cc_id
        groups[group_key]["total_stock_amount"] = round(
            groups[group_key]["total_stock_amount"] + stock_amount, 2
        )
        groups[group_key]["items"].append({
            "item_code": code,
            "item_name": item.item_name if item else None,
            "unit": (
                item.unit.unit_name
                if item and item.unit
                else None
            ),
            "received_qty": received_qty,
            "issued_qty": issued_qty,
            "stock_qty": stock_qty,
            "stock_amount": stock_amount,
        })

    # assign sl_no after grouping
    result = []
    for group_sl, group_data in enumerate(groups.values(), start=1):
        items_with_sl = []
        for item_sl, item_row in enumerate(group_data["items"], start=1):
            items_with_sl.append({
                "sl_no": f"{group_sl}.{item_sl}",
                **item_row,
            })
        result.append({
            "sl_no": group_sl,
            "cc_code": group_data["cc_code"],
            "cc_name": group_data["cc_name"],
            "total_stock_amount": group_data["total_stock_amount"],
            "items": items_with_sl,
        })

    return res("Stock list fetched", result, 200)


# ══════════════════════════════════════════════════════════════════
# STOCK ITEM DETAIL  —  GRN & GIN breakdown, with search + date range
# ══════════════════════════════════════════════════════════════════

def _build_item_detail(project_code, item_code, from_date=None, to_date=None):
    """
    Returns detail dict for one item_code with optional date-range filter
    on GRN/GIN entries.
    """
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

    grn_entries = []
    total_received_qty = 0.0
    total_received_amount = 0.0
    for r in grn_q.order_by(GrnMaster.grn_date).all():
        qty = float(r.current_received_qty or 0)
        rate = float(r.rate or 0)
        amount = round(qty * rate, 2)
        total_received_qty += qty
        total_received_amount += amount
        grn_entries.append({
            "grn_no": r.grn_no,
            "grn_date": _fmt_date(r.grn_date),
            "received_qty": qty,
            "rate": rate,
            "amount": amount,
            "store_location": r.store_location,
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

    gin_entries = []
    total_issued_qty = 0.0
    total_issued_amount = 0.0
    for r in gin_q.order_by(GinMaster.gin_date).all():
        qty = float(r.issue_qty or 0)
        rate = float(r.rate or 0)
        amount = round(qty * rate, 2)
        total_issued_qty += qty
        total_issued_amount += amount
        gin_entries.append({
            "gin_no": r.gin_no,
            "gin_date": _fmt_date(r.gin_date),
            "issued_qty": qty,
            "rate": rate,
            "amount": amount,
            "item_used_location": r.item_used_location,
        })

    # ── item master ──────────────────────────────────────────────
    item = db.session.query(Item).filter(Item.item_code == item_code).first()

    return {
        "summary": {
            "item_code": item_code,
            "item_name": item.item_name if item else None,
            "unit": (
                item.unit.unit_name
                if item and item.unit
                else None
            ),
            "total_received_qty": round(total_received_qty, 2),
            "total_received_amount": round(total_received_amount, 2),
            "total_issued_qty": round(total_issued_qty, 2),
            "total_issued_amount": round(total_issued_amount, 2),
            "stock_qty": round(total_received_qty - total_issued_qty, 2),
            "stock_amount": round(total_received_amount - total_issued_amount, 2),
        },
        "grn_entries": grn_entries,
        "gin_entries": gin_entries,
    }


def get_stock_item_detail(project_code, item_code=None, search=None,
                          from_date=None, to_date=None):
    """
    Params:
      item_code  – exact match (direct navigation)
      search     – partial case-insensitive match on item_code OR item_name
      from_date  – filter GRN/GIN entries on or after this date (YYYY-MM-DD)
      to_date    – filter GRN/GIN entries on or before this date (YYYY-MM-DD)

    If search is provided, returns detail for every matching item.
    If item_code is provided (and no search), returns detail for that one item.
    """
    if search:
        keyword = f"%{search}%"
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
            _build_item_detail(project_code, i.item_code, from_date, to_date)
            for i in matched_items
        ]
        return res("Stock item detail fetched", result, 200)

    if item_code:
        detail = _build_item_detail(project_code, item_code, from_date, to_date)
        return res("Stock item detail fetched", detail, 200)

    return res("item_code or search is required", [], 400)
