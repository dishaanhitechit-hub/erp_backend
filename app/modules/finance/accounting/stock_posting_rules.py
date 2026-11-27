"""
Stock posting rules for GRN and GIN — C6.

GRN (stock-in):
  Dr Item's CC code (via Item.cc_code_id)  — per item line
  Cr Vendor payable                        — total GRN value
  Stock ledger: +qty at PO rate

GIN (stock-out):
  Dr Item's CC code  — per item line at WAC rate
  Cr Item's CC code  — per item line at WAC rate (stock reduction)
  Stock ledger: -qty at WAC rate

Rate lookup:
  GRN: GrnItem.order_item_id → OrderItem.rate
  GIN: WAC from stock_ledger_service.get_gin_item_rate()

CC resolution: each item's CC is looked up from the Item master's cc_code_id,
which maps to the correct Stock-in-Hand CC (DRMC, DRMH, etc.). Falls back to
"DRMC" only when the item has no cc_code_id set.
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


def _item_cc(item_code_str, cc_map=None):
    """Resolve CC from Item master's cc_code_id. Returns (cc_id, cc_code_str).
    When cc_map is provided (from _build_item_cc_map), uses it for O(1) lookup."""
    if cc_map is not None:
        return cc_map.get(item_code_str) or _resolve_cc_id("DRMC")
    if not item_code_str:
        return _resolve_cc_id("DRMC")
    from app.models.item import Item
    item = Item.query.filter_by(item_code=item_code_str).first()
    if item and item.cc_code_id:
        from app.models.cc_code import CCCode
        cc = CCCode.query.get(item.cc_code_id)
        if cc:
            return cc.id, cc.cc_code
    return _resolve_cc_id("DRMC")


def _build_item_cc_map(item_codes):
    """Batch-load Item → CCCode mapping. Returns {item_code: (cc_id, cc_code)}."""
    if not item_codes:
        return {}
    from app.models.item import Item
    from app.models.cc_code import CCCode
    items = Item.query.filter(Item.item_code.in_(list(item_codes))).all()
    cc_ids = {i.cc_code_id for i in items if i.cc_code_id}
    cc_objs = {cc.id: cc for cc in CCCode.query.filter(CCCode.id.in_(list(cc_ids))).all()} if cc_ids else {}
    result = {}
    for i in items:
        cc = cc_objs.get(i.cc_code_id)
        if cc:
            result[i.item_code] = (cc.id, cc.cc_code)
    return result


# ─────────────────────────────────────────────────────────────────
# GRN posting rule (accounting entries)
# ─────────────────────────────────────────────────────────────────

def post_grn_accounting(source_id):
    """
    GRN is a stock-management document — it updates the stock ledger only.

    Accounting (Dr CC / Cr Vendor) is deferred to the linked Purchase Bill,
    which carries the vendor's actual invoice amount and is the authoritative
    trigger for the financial books.  Raising both entries would double-count
    the CC expense and the vendor payable (confirmed in reconciliation: GRN and
    PB each debited the same CC code for the same items).
    """
    # Return no-op — post_grn_stock handles the stock ledger separately.
    return None, []

    # ── DEAD CODE BELOW — kept for reference ──────────────────────────────
    # Previous implementation: Dr CC / Cr Vendor per GRN receipt.
    # Removed because Purchase Bill already posts Dr CC / Cr Vendor,
    # creating duplicate entries in the accounting ledger.
    from app.models.grnMaster import GrnMaster

    grn = GrnMaster.query.get(source_id)
    if not grn:
        from .posting_engine import PostingError
        raise PostingError(f"GRN {source_id} not found")

    # Batch-load OrderItems and Item→CC mapping
    oi_ids = [item.order_item_id for item in grn.items if item.order_item_id]
    oi_map = {}
    if oi_ids:
        for oi in OrderItem.query.filter(OrderItem.id.in_(oi_ids)).all():
            oi_map[oi.id] = oi

    all_item_codes = set()
    for item in grn.items:
        if item.item_code:
            all_item_codes.add(item.item_code)
        oi = oi_map.get(item.order_item_id)
        if oi and oi.item_code:
            all_item_codes.add(oi.item_code)
    cc_map = _build_item_cc_map(all_item_codes)

    lines = []
    total = Decimal("0")

    for item in grn.items:
        qty = _d(item.current_received_qty)
        if qty <= 0:
            continue

        rate = Decimal("0")
        item_code = item.item_code
        oi = oi_map.get(item.order_item_id)
        if oi:
            rate = _d(oi.rate)
            if not item_code:
                item_code = oi.item_code

        amt = (qty * rate).quantize(Decimal("0.01"))
        if amt <= 0:
            continue

        cc_id, cc_code = _item_cc(item_code, cc_map)
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
    Dr CC-code (cost_head from GIN), Cr same CC (stock reduction) per item at WAC rate.
    """
    from app.models.ginMaster import GinMaster
    from .stock_ledger_service import get_gin_item_rate

    gin = GinMaster.query.get(source_id)
    if not gin:
        from .posting_engine import PostingError
        raise PostingError(f"GIN {source_id} not found")

    # Batch-load OrderItems and Item→CC mapping
    oi_ids = [item.order_item_id for item in gin.items if item.order_item_id]
    oi_map = {}
    if oi_ids:
        for oi in OrderItem.query.filter(OrderItem.id.in_(oi_ids)).all():
            oi_map[oi.id] = oi

    all_item_codes = {oi.item_code for oi in oi_map.values() if oi.item_code}
    cc_map = _build_item_cc_map(all_item_codes)

    lines = []
    total = Decimal("0")

    for item in gin.items:
        qty = _d(item.issue_qty)
        if qty <= 0:
            continue

        item_id = item.order_item_id
        item_code = None
        oi = oi_map.get(item_id)
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

        cc_id, cc_code = _item_cc(item_code, cc_map)
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

        lines.append({
            "account_type": "CC",
            "cc_id": cc_id,
            "dr_cr": "Cr",
            "amount": amt,
            "project_code": gin.project_code,
            "cost_centre_code": cc_code,
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

    # Batch-load OrderItems
    oi_ids = [item.order_item_id for item in grn.items if item.order_item_id]
    oi_map = {}
    if oi_ids:
        for oi in OrderItem.query.filter(OrderItem.id.in_(oi_ids)).all():
            oi_map[oi.id] = oi

    entries = []
    for item in grn.items:
        qty = _d(item.current_received_qty)
        if qty <= 0:
            continue

        rate = Decimal("0")
        item_code = item.item_code
        oi = oi_map.get(item.order_item_id)
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

    # Batch-load OrderItems
    oi_ids = [item.order_item_id for item in gin.items if item.order_item_id]
    oi_map = {}
    if oi_ids:
        for oi in OrderItem.query.filter(OrderItem.id.in_(oi_ids)).all():
            oi_map[oi.id] = oi

    entries = []
    for item in gin.items:
        qty = _d(item.issue_qty)
        if qty <= 0:
            continue

        item_id = item.order_item_id
        item_code = None
        oi = oi_map.get(item_id)
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
