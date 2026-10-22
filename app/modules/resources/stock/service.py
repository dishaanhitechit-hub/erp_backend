from decimal import Decimal
from collections import defaultdict
from sqlalchemy import func
from app.extensions import db

from app.models.grnMaster import GrnMaster, GrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.models.orderMaster import OrderItem
from app.models.item import Item
from app.models.asset import Asset
from app.models.cc_code import CCCode
from app.response import res


def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════
# STOCK LIST  —  grouped by CC Code
# ══════════════════════════════════════════════════════════════════

def get_stock_list(project_code, item_category=None, page=1, limit=10, cc_codes=None):

    # ── received from GRN ────────────────────────────────────────
    grn_q = (
        db.session.query(
            OrderItem.item_code.label("item_code"),
            OrderItem.asset_code.label("asset_code"),
            OrderItem.is_asset.label("is_asset"),
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

    grn_rows = grn_q.group_by(
        OrderItem.item_code, OrderItem.asset_code, OrderItem.is_asset
    ).all()

    if not grn_rows:
        return res("Stock list fetched", [], 200)

    normal_codes = [r.item_code  for r in grn_rows if not r.is_asset and r.item_code]
    asset_codes  = [r.asset_code for r in grn_rows if r.is_asset and r.asset_code]

    # ── issued from GIN ──────────────────────────────────────────
    gin_filter = []
    if normal_codes:
        gin_filter.append(OrderItem.item_code.in_(normal_codes))
    if asset_codes:
        gin_filter.append(OrderItem.asset_code.in_(asset_codes))

    gin_q = (
        db.session.query(
            OrderItem.item_code.label("item_code"),
            OrderItem.asset_code.label("asset_code"),
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
            db.or_(*gin_filter) if gin_filter else db.false(),
        )
    )
    if item_category:
        gin_q = gin_q.filter(GinMaster.item_category == item_category)

    gin_map = {
        (r.item_code, r.asset_code): r
        for r in gin_q.group_by(OrderItem.item_code, OrderItem.asset_code).all()
    }

    # ── item master (normal + asset) ─────────────────────────────
    item_map = (
        {i.item_code: i for i in db.session.query(Item).filter(Item.item_code.in_(normal_codes)).all()}
        if normal_codes else {}
    )
    asset_map = (
        {a.asset_code: a for a in db.session.query(Asset).filter(Asset.asset_code.in_(asset_codes)).all()}
        if asset_codes else {}
    )

    # ── CC code map ──────────────────────────────────────────────
    cc_ids = (
        [item_map[c].cc_code_id  for c in normal_codes if c in item_map and item_map[c].cc_code_id] +
        [asset_map[c].cc_code_id for c in asset_codes  if c in asset_map and asset_map[c].cc_code_id]
    )
    cc_map = (
        {cc.id: cc for cc in db.session.query(CCCode).filter(CCCode.id.in_(cc_ids)).all()}
        if cc_ids else {}
    )

    # ── group by CC code ─────────────────────────────────────────
    groups = defaultdict(lambda: {"items": [], "totalStockAmount": Decimal('0')})

    for row in grn_rows:
        if row.is_asset:
            code      = row.asset_code
            master    = asset_map.get(code)
            item_name = master.asset_name if master else None
        else:
            code      = row.item_code
            master    = item_map.get(code)
            item_name = master.item_name if master else None

        gin = gin_map.get((row.item_code, row.asset_code))

        receivedQty = Decimal(str(row.total_received_qty or 0))
        receivedAmt = Decimal(str(row.total_received_amount or 0))
        issuedQty   = Decimal(str(gin.total_issued_qty or 0)) if gin else Decimal('0')
        issuedAmt   = Decimal(str(gin.total_issued_amount or 0)) if gin else Decimal('0')

        stockQty    = receivedQty - issuedQty
        stockAmount = receivedAmt - issuedAmt

        cc_id     = master.cc_code_id if master else None
        cc        = cc_map.get(cc_id) if cc_id else None
        group_key = cc_id or "__none__"

        groups[group_key]["ccCode"] = cc.cc_code if cc else None
        groups[group_key]["ccName"] = cc.cc_name if cc else None
        groups[group_key]["totalStockAmount"] = groups[group_key]["totalStockAmount"] + stockAmount
        groups[group_key]["items"].append({
            "itemCode":    code,
            "itemName":    item_name,
            "unit":        master.unit.unit_name if master and master.unit else None,
            "isAsset":     bool(row.is_asset),
            "receivedQty": float(receivedQty),
            "issuedQty":   float(issuedQty),
            "stockQty":    float(stockQty),
            "stockAmount": float(stockAmount),
        })

    # ── filter by cc_codes (case-insensitive, multi-value) ───────
    if cc_codes:
        allowed = {c.lower() for c in cc_codes}
        groups = {
            k: v for k, v in groups.items()
            if v.get("ccCode") and v["ccCode"].lower() in allowed
        }

    # ── build full list with slNo ────────────────────────────────
    all_groups = []
    for group_sl, group_data in enumerate(groups.values(), start=1):
        all_groups.append({
            "slNo":             group_sl,
            "ccCode":           group_data["ccCode"],
            "ccName":           group_data["ccName"],
            "totalStockAmount": float(group_data["totalStockAmount"]),
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


def _build_item_detail(project_code, item_code, is_asset=False, from_date=None, to_date=None,
                       grn_page=1, gin_page=1, entries_limit=10):

    item_filter = (
        (OrderItem.asset_code == item_code) if is_asset
        else (OrderItem.item_code == item_code)
    )

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
            item_filter,
        )
    )
    if from_date:
        grn_q = grn_q.filter(GrnMaster.grn_date >= from_date)
    if to_date:
        grn_q = grn_q.filter(GrnMaster.grn_date <= to_date)

    grn_entries         = []
    total_received_qty  = Decimal('0')
    total_received_amt  = Decimal('0')
    for r in grn_q.order_by(GrnMaster.grn_date).all():
        qty    = Decimal(str(r.current_received_qty or 0))
        rate   = Decimal(str(r.rate or 0))
        amount = qty * rate
        total_received_qty += qty
        total_received_amt += amount
        grn_entries.append({
            "grnNo":         r.grn_no,
            "grnDate":       _fmt_date(r.grn_date),
            "receivedQty":   float(qty),
            "rate":          float(rate),
            "amount":        float(amount),
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
            item_filter,
            GinItem.order_item_id.isnot(None),
        )
    )
    if from_date:
        gin_q = gin_q.filter(GinMaster.gin_date >= from_date)
    if to_date:
        gin_q = gin_q.filter(GinMaster.gin_date <= to_date)

    gin_entries        = []
    total_issued_qty   = Decimal('0')
    total_issued_amt   = Decimal('0')
    for r in gin_q.order_by(GinMaster.gin_date).all():
        qty    = Decimal(str(r.issue_qty or 0))
        rate   = Decimal(str(r.rate or 0))
        amount = qty * rate
        total_issued_qty += qty
        total_issued_amt += amount
        gin_entries.append({
            "ginNo":       r.gin_no,
            "ginDate":     _fmt_date(r.gin_date),
            "issuedQty":   float(qty),
            "rate":        float(rate),
            "amount":      float(amount),
            "useLocation": r.item_used_location,
        })

    # ── item master ──────────────────────────────────────────────
    if is_asset:
        master     = db.session.query(Asset).filter(Asset.asset_code == item_code).first()
        item_name  = master.asset_name if master else None
        item_unit  = master.unit.unit_name if master and master.unit else None
    else:
        master     = db.session.query(Item).filter(Item.item_code == item_code).first()
        item_name  = master.item_name if master else None
        item_unit  = master.unit.unit_name if master and master.unit else None

    return {
        "summary": {
            "itemCode":            item_code,
            "itemName":            item_name,
            "unit":                item_unit,
            "isAsset":             is_asset,
            "totalReceivedQty":    float(total_received_qty),
            "totalReceivedAmount": float(total_received_amt),
            "totalIssuedQty":      float(total_issued_qty),
            "totalIssuedAmount":   float(total_issued_amt),
            "stockQty":            float(total_received_qty - total_issued_qty),
            "stockAmount":         float(total_received_amt - total_issued_amt),
        },
        "grnEntries": _paginate(grn_entries, grn_page, entries_limit),
        "ginEntries": _paginate(gin_entries, gin_page, entries_limit),
    }


def get_stock_item_detail(project_code, item_code=None, is_asset=False, search=None,
                          from_date=None, to_date=None,
                          grn_page=1, gin_page=1, entries_limit=10):

    if search:
        keyword = f"%{search}%"
        normal_items = (
            db.session.query(Item)
            .filter(db.or_(Item.item_code.ilike(keyword), Item.item_name.ilike(keyword)))
            .all()
        )
        asset_items = (
            db.session.query(Asset)
            .filter(db.or_(Asset.asset_code.ilike(keyword), Asset.asset_name.ilike(keyword)))
            .all()
        )
        if not normal_items and not asset_items:
            return res("No items found matching search", [], 200)

        result = (
            [_build_item_detail(project_code, i.item_code, False, from_date, to_date,
                                grn_page, gin_page, entries_limit) for i in normal_items] +
            [_build_item_detail(project_code, a.asset_code, True, from_date, to_date,
                                grn_page, gin_page, entries_limit) for a in asset_items]
        )
        return res("Stock item detail fetched", result, 200)

    if item_code:
        detail = _build_item_detail(project_code, item_code, is_asset, from_date, to_date,
                                    grn_page, gin_page, entries_limit)
        return res("Stock item detail fetched", detail, 200)

    return res("itemCode or search is required", [], 400)
