"""
Stock posting rules for GRN and GIN — C6.

GRN (stock-in):
  Dr CARM (raw materials / current asset)   — per item line
  Cr Vendor payable                         — total GRN value
  Stock ledger: +qty at PO rate

GIN (stock-out):
  Dr CC code from GIN cost_head             — per item line at WAC rate
  Cr CARM (raw materials consumed)          — per item line at WAC rate
  Stock ledger: -qty at WAC rate

Rate lookup:
  GRN: GrnItem.order_item_id → OrderItem.rate
  GIN: WAC from stock_ledger_service.get_gin_item_rate()

CC Head hierarchy is preserved: GinMaster.cost_head carries the CC code
which maps to CC Head → Group → Subgroup → CC Code in reporting.
"""

from decimal import Decimal

from app.models.orderMaster import OrderItem


def _d(val):
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _resolve_cc_id(cc_code_str):
    if not cc_code_str:
        return None, None
    from app.models.cc_code import CCCode
    cc = CCCode.query.filter(CCCode.cc_code == cc_code_str.upper().strip()).first()
    return (cc.id if cc else None), cc_code_str.upper().strip()


# ─────────────────────────────────────────────────────────────────
# GRN posting rule (accounting entries)
# ─────────────────────────────────────────────────────────────────

def post_grn_accounting(source_id):
    """
    Build accounting posting data for an approved GRN.
    Dr CARM (inventory asset) per item, Cr Vendor payable for total.
    """
    from app.models.grnMaster import GrnMaster

    grn = GrnMaster.query.get(source_id)
    if not grn:
        from .posting_engine import PostingError
        raise PostingError(f"GRN {source_id} not found")

    lines = []
    total = Decimal("0")

    for item in grn.items:
        qty = _d(item.current_received_qty)
        if qty <= 0:
            continue

        rate = Decimal("0")
        if item.order_item_id:
            oi = OrderItem.query.get(item.order_item_id)
            if oi:
                rate = _d(oi.rate)

        amt = (qty * rate).quantize(Decimal("0.01"))
        if amt <= 0:
            continue

        cc_id, cc_code = _resolve_cc_id("CARM")
        lines.append({
            "account_type": "CC",
            "cc_id": cc_id,
            "dr_cr": "Dr",
            "amount": amt,
            "project_code": grn.project_code,
            "cost_centre_code": cc_code,
            "source_line_id": item.id,
            "narration": f"GRN stock-in: {item.item_code or ''} qty={qty}",
        })
        total += amt

    if total > 0 and grn.vendor_id:
        lines.append({
            "account_type": "Vendor",
            "vendor_id": grn.vendor_id,
            "dr_cr": "Cr",
            "amount": total,
            "project_code": grn.project_code,
            "narration": f"Vendor payable: GRN {grn.grn_no}",
        })

    header = {
        "posting_date": grn.grn_date,
        "voucher_no": grn.grn_no,
        "project_code": grn.project_code,
        "remarks": None,
    }
    return header, lines


# ─────────────────────────────────────────────────────────────────
# GIN posting rule (accounting entries)
# ─────────────────────────────────────────────────────────────────

def post_gin_accounting(source_id):
    """
    Build accounting posting data for an approved GIN.
    Dr CC-code (cost_head from GIN), Cr CARM per item at WAC rate.
    """
    from app.models.ginMaster import GinMaster
    from .stock_ledger_service import get_gin_item_rate

    gin = GinMaster.query.get(source_id)
    if not gin:
        from .posting_engine import PostingError
        raise PostingError(f"GIN {source_id} not found")

    lines = []
    total = Decimal("0")
    cost_head_code = gin.cost_head or gin.cost_factor or "DRMC"

    for item in gin.items:
        qty = _d(item.issue_qty)
        if qty <= 0:
            continue

        item_id = item.order_item_id
        item_code = None
        if item_id:
            oi = OrderItem.query.get(item_id)
            if oi:
                item_code = oi.item_code

        rate = get_gin_item_rate(
            item_id=item_id,
            project_code=gin.project_code,
            location_id=item.stock_location,
        )
        amt = (qty * rate).quantize(Decimal("0.01"))
        if amt <= 0:
            continue

        cc_id, cc_code = _resolve_cc_id(cost_head_code)
        lines.append({
            "account_type": "CC",
            "cc_id": cc_id,
            "dr_cr": "Dr",
            "amount": amt,
            "project_code": gin.project_code,
            "cost_centre_code": cc_code,
            "source_line_id": item.id,
            "narration": f"GIN consumption: {item_code or ''} qty={qty}",
        })

        carm_id, carm_code = _resolve_cc_id("CARM")
        lines.append({
            "account_type": "CC",
            "cc_id": carm_id,
            "dr_cr": "Cr",
            "amount": amt,
            "project_code": gin.project_code,
            "cost_centre_code": carm_code,
            "source_line_id": item.id,
            "narration": f"Inventory consumed: {item_code or ''} qty={qty}",
        })

        total += amt

    header = {
        "posting_date": gin.gin_date,
        "voucher_no": gin.gin_no,
        "project_code": gin.project_code,
        "remarks": None,
    }
    return header, lines


# ─────────────────────────────────────────────────────────────────
# Stock ledger entries (called from GRN/GIN approval hooks)
# ─────────────────────────────────────────────────────────────────

def post_grn_stock(grn_id, user_id=None):
    """
    Create stock-in entries for each GRN item.
    Rate = PO rate from OrderItem.rate.
    """
    from app.models.grnMaster import GrnMaster
    from .stock_ledger_service import post_stock_entry

    grn = GrnMaster.query.get(grn_id)
    if not grn:
        return []

    entries = []
    for item in grn.items:
        qty = _d(item.current_received_qty)
        if qty <= 0:
            continue

        rate = Decimal("0")
        item_code = item.item_code
        if item.order_item_id:
            oi = OrderItem.query.get(item.order_item_id)
            if oi:
                rate = _d(oi.rate)
                if not item_code:
                    item_code = oi.item_code

        entry = post_stock_entry(
            source_type="grn",
            source_id=grn.id,
            source_line_id=item.id,
            transaction_date=grn.grn_date,
            item_id=item.order_item_id or item.id,
            item_code=item_code,
            project_code=grn.project_code,
            location_id=item.store_location,
            quantity=qty,
            rate=rate,
            user_id=user_id,
        )
        if entry:
            entries.append(entry)

    return entries


def post_gin_stock(gin_id, user_id=None):
    """
    Create stock-out entries for each GIN item.
    Rate = WAC from stock_ledger_service.get_gin_item_rate().
    Quantity is stored as NEGATIVE (stock-out).
    """
    from app.models.ginMaster import GinMaster
    from .stock_ledger_service import post_stock_entry, get_gin_item_rate

    gin = GinMaster.query.get(gin_id)
    if not gin:
        return []

    entries = []
    for item in gin.items:
        qty = _d(item.issue_qty)
        if qty <= 0:
            continue

        item_id = item.order_item_id
        item_code = None
        if item_id:
            oi = OrderItem.query.get(item_id)
            if oi:
                item_code = oi.item_code

        rate = get_gin_item_rate(
            item_id=item_id,
            project_code=gin.project_code,
            location_id=item.stock_location,
        )

        entry = post_stock_entry(
            source_type="gin",
            source_id=gin.id,
            source_line_id=item.id,
            transaction_date=gin.gin_date,
            item_id=item_id or item.id,
            item_code=item_code,
            project_code=gin.project_code,
            location_id=item.stock_location,
            quantity=-qty,
            rate=rate,
            user_id=user_id,
        )
        if entry:
            entries.append(entry)

    return entries
