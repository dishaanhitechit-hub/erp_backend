"""
Stock Ledger Service — C5 + C7 + C8.

Provides:
  - post_stock_entry()   — records a stock-in or stock-out entry
  - reverse_stock_entry() — creates a reversal entry (quantity negated)
  - get_wac()            — returns current WAC rate for (project, location, item)
  - recalculate_running_balances() — forward-recalculate from a correction point

Costing level: Project + Stock Location + Item  (as per C7 requirement).
GIN rate = running_value / running_qty from WAC   (C8 requirement).

Must be called INSIDE an active db.session (after flush, before commit).
Requires the stock_ledger table to exist in the database.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date as date_type

from app.extensions import db
from app.models.stockLedger import StockLedger
from app.models.accounting import FinancialYear


class StockLedgerError(Exception):
    pass


def _d(val):
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _resolve_fy(txn_date):
    if not isinstance(txn_date, date_type):
        return None
    fy = FinancialYear.query.filter(
        FinancialYear.start_date <= txn_date,
        FinancialYear.end_date >= txn_date,
    ).first()
    return fy.id if fy else None


def _already_posted(source_type, source_id, source_line_id):
    return StockLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        is_reversal=False,
    ).first()


def _latest_running(item_id, project_code, location_id, before_date=None, before_id=None):
    """
    Get the most recent stock ledger entry for (item, project, location)
    to read running_qty and running_value.
    """
    q = StockLedger.query.filter_by(
        item_id=item_id,
        project_code=project_code,
        location_id=location_id,
    )
    if before_date:
        q = q.filter(StockLedger.transaction_date <= before_date)
    if before_id:
        q = q.filter(StockLedger.id < before_id)
    return q.order_by(
        StockLedger.transaction_date.desc(),
        StockLedger.id.desc(),
    ).first()


# ─────────────────────────────────────────────────────────────────
# C5: Post stock entry
# ─────────────────────────────────────────────────────────────────

def post_stock_entry(
    source_type,
    source_id,
    source_line_id,
    transaction_date,
    item_id,
    item_code,
    project_code,
    location_id,
    quantity,
    rate,
    user_id=None,
    item_description=None,
):
    """
    Record a stock movement.

    quantity > 0 → stock IN  (GRN)
    quantity < 0 → stock OUT (GIN)
    rate: for GRN = PO rate; for GIN = WAC rate from get_wac()

    Returns the created StockLedger row or None if already posted.
    """
    if _already_posted(source_type, source_id, source_line_id):
        return None

    qty = _d(quantity)
    unit_rate = _d(rate)
    amt = (qty * unit_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    prev = _latest_running(item_id, project_code, location_id)
    prev_qty = _d(prev.running_qty) if prev else Decimal("0")
    prev_val = _d(prev.running_value) if prev else Decimal("0")

    running_qty = prev_qty + qty
    running_value = prev_val + amt

    entry = StockLedger(
        transaction_date=transaction_date,
        financial_year_id=_resolve_fy(transaction_date),
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        item_id=item_id,
        item_code=item_code,
        item_description=item_description,
        project_code=project_code,
        location_id=location_id,
        quantity=qty,
        rate=unit_rate,
        amount=amt,
        running_qty=running_qty,
        running_value=running_value,
        is_reversal=False,
        created_by=user_id,
    )
    db.session.add(entry)
    db.session.flush()

    return entry


# ─────────────────────────────────────────────────────────────────
# C5: Reverse stock entry
# ─────────────────────────────────────────────────────────────────

def reverse_stock_entry(source_type, source_id, user_id=None):
    """
    Create reversal entries for all stock lines of a source document.
    Uses SELECT FOR UPDATE to prevent duplicate reversals.
    Returns list of reversal StockLedger rows, or empty list.
    """
    originals = StockLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=False,
    ).with_for_update().all()

    if not originals:
        return []

    reversals = []
    for orig in originals:
        existing = StockLedger.query.filter_by(
            reversed_stock_entry_id=orig.id,
            is_reversal=True,
        ).first()
        if existing:
            continue

        rev_qty = -_d(orig.quantity)
        rev_amt = -_d(orig.amount)

        prev = _latest_running(
            orig.item_id, orig.project_code, orig.location_id
        )
        prev_qty = _d(prev.running_qty) if prev else Decimal("0")
        prev_val = _d(prev.running_value) if prev else Decimal("0")

        rev = StockLedger(
            transaction_date=orig.transaction_date,
            financial_year_id=orig.financial_year_id,
            source_type=source_type,
            source_id=source_id,
            source_line_id=orig.source_line_id,
            item_id=orig.item_id,
            item_code=orig.item_code,
            item_description=orig.item_description,
            project_code=orig.project_code,
            location_id=orig.location_id,
            quantity=rev_qty,
            rate=_d(orig.rate),
            amount=rev_amt,
            running_qty=prev_qty + rev_qty,
            running_value=prev_val + rev_amt,
            is_reversal=True,
            reversed_stock_entry_id=orig.id,
            created_by=user_id,
        )
        db.session.add(rev)
        reversals.append(rev)

    if reversals:
        db.session.flush()
        items_to_recalc = {
            (r.item_id, r.project_code, r.location_id) for r in reversals
        }
        for item_id, project_code, location_id in items_to_recalc:
            recalculate_running_balances(
                item_id, project_code, location_id,
                from_date=reversals[0].transaction_date,
            )

    return reversals


# ─────────────────────────────────────────────────────────────────
# C7: Moving Weighted Average Cost
# ─────────────────────────────────────────────────────────────────

def get_wac(item_id, project_code, location_id):
    """
    Return the current WAC rate for (item, project, location).

    WAC = running_value / running_qty from the latest stock ledger entry.
    Returns Decimal("0") if no stock exists or running_qty <= 0.
    """
    latest = _latest_running(item_id, project_code, location_id)
    if not latest:
        return Decimal("0")
    rq = _d(latest.running_qty)
    rv = _d(latest.running_value)
    if rq <= 0:
        return Decimal("0")
    return (rv / rq).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recalculate_running_balances(item_id, project_code, location_id, from_date=None):
    """
    Forward-recalculate running_qty and running_value from a correction point.

    Entry fields (quantity, rate, amount) are IMMUTABLE.
    Only running balance fields are updated.

    This is needed after:
      - A backdated entry is inserted
      - A reversal is posted for a past entry
    """
    q = StockLedger.query.filter_by(
        item_id=item_id,
        project_code=project_code,
        location_id=location_id,
    ).order_by(
        StockLedger.transaction_date.asc(),
        StockLedger.id.asc(),
    )

    if from_date:
        before_entry = StockLedger.query.filter_by(
            item_id=item_id,
            project_code=project_code,
            location_id=location_id,
        ).filter(
            StockLedger.transaction_date < from_date,
        ).order_by(
            StockLedger.transaction_date.desc(),
            StockLedger.id.desc(),
        ).first()

        running_qty = _d(before_entry.running_qty) if before_entry else Decimal("0")
        running_value = _d(before_entry.running_value) if before_entry else Decimal("0")

        q = q.filter(StockLedger.transaction_date >= from_date)
    else:
        running_qty = Decimal("0")
        running_value = Decimal("0")

    for entry in q.all():
        running_qty += _d(entry.quantity)
        running_value += _d(entry.amount)
        entry.running_qty = running_qty
        entry.running_value = running_value


# ─────────────────────────────────────────────────────────────────
# C8: GIN Rate Lookup (connects to WAC)
# ─────────────────────────────────────────────────────────────────

def get_gin_item_rate(item_id, project_code, location_id):
    """
    Return the rate to use for a GIN (stock-out) line.
    This is the WAC rate: running_value / running_qty.

    Falls back to Decimal("0") when no stock exists at that location.
    The caller should raise an error if zero-rate stock-outs are not allowed.
    """
    return get_wac(item_id, project_code, location_id)


def get_stock_balance(item_id, project_code, location_id):
    """
    Return (running_qty, running_value, wac_rate) for a stock position.
    Useful for reports and validation before issuing stock.
    """
    latest = _latest_running(item_id, project_code, location_id)
    if not latest:
        return Decimal("0"), Decimal("0"), Decimal("0")
    rq = _d(latest.running_qty)
    rv = _d(latest.running_value)
    wac = (rv / rq).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if rq > 0 else Decimal("0")
    return rq, rv, wac
