"""
Central Accounting Posting Engine.

Every financial document posts here on approval. Each posting creates one
AccountingLedger header + balanced AccountingLedgerLine rows.
"""

from decimal import Decimal
from datetime import date as date_type

from app.extensions import db
from app.models.accounting import (
    AccountingLedger,
    AccountingLedgerLine,
    FinancialYear,
)


class PostingError(Exception):
    pass


def _resolve_fy(posting_date):
    """Return the financial_year_id for a given date, or None."""
    fy = FinancialYear.query.filter(
        FinancialYear.start_date <= posting_date,
        FinancialYear.end_date >= posting_date,
    ).first()
    return fy.id if fy else None


def active_posting(source_type, source_id, for_update=False):
    """
    The document's ACTIVE posting: an original (not a reversal) that has not
    been reversed. None when the document is not in the books right now
    (never posted, or posted and then reversed by reback / cancel).
    """
    q = AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=False,
        is_reversed=False,
    )
    if for_update:
        q = q.with_for_update()
    return q.first()


def _already_posted(source_type, source_id):
    """Check if an active (not reversed) posting already exists."""
    return active_posting(source_type, source_id)


def post_document(source_type, source_id, user_id=None):
    """
    Post a source document to the accounting ledger.

    Must be called INSIDE an active db.session (after flush, before commit).
    Returns the created AccountingLedger instance, or None if already posted.
    Raises PostingError on validation failure.
    """
    if _already_posted(source_type, source_id):
        return None

    from .posting_rules import get_posting_rules
    rules_fn = get_posting_rules(source_type)
    if not rules_fn:
        raise PostingError(f"No posting rules for source_type='{source_type}'")

    header_data, lines_data = rules_fn(source_id)

    if header_data is None or not lines_data:
        return None

    total_dr = sum(Decimal(str(l["amount"])) for l in lines_data if l["dr_cr"] == "Dr")
    total_cr = sum(Decimal(str(l["amount"])) for l in lines_data if l["dr_cr"] == "Cr")

    if total_dr != total_cr:
        diff = abs(total_dr - total_cr)
        if diff <= Decimal("1.00"):
            side = "Dr" if total_cr > total_dr else "Cr"
            lines_data.append({
                "account_type": "CC",
                "cc_code": "ROFE" if side == "Dr" else "ROFI",
                "dr_cr": side,
                "amount": diff,
                "project_code": header_data.get("project_code"),
                "narration": f"Auto round-off adjustment ({diff})",
            })
            if side == "Dr":
                total_dr += diff
            else:
                total_cr += diff
        else:
            raise PostingError(
                f"Unbalanced entry for {source_type}:{source_id}: "
                f"Dr={total_dr}, Cr={total_cr}"
            )

    if total_dr == 0:
        raise PostingError(f"Zero-amount entry for {source_type}:{source_id}")

    posting_date = header_data["posting_date"]
    fy_id = _resolve_fy(posting_date) if isinstance(posting_date, date_type) else None

    ledger = AccountingLedger(
        posting_date=posting_date,
        financial_year_id=fy_id,
        source_type=source_type,
        source_id=source_id,
        voucher_no=header_data["voucher_no"],
        project_code=header_data.get("project_code"),
        remarks=header_data.get("remarks"),
        is_reversal=False,
        total_debit=total_dr,
        total_credit=total_cr,
        created_by=user_id,
    )
    db.session.add(ledger)
    db.session.flush()

    for idx, line in enumerate(lines_data, start=1):
        db.session.add(AccountingLedgerLine(
            posting_id=ledger.id,
            sl_no=idx,
            account_type=line["account_type"],
            cc_id=line.get("cc_id"),
            vendor_id=line.get("vendor_id"),
            bank_cash_id=line.get("bank_cash_id"),
            dr_cr=line["dr_cr"],
            amount=Decimal(str(line["amount"])),
            project_code=line.get("project_code"),
            cost_centre_code=line.get("cost_centre_code"),
            gst_type=line.get("gst_type"),
            gst_rate=line.get("gst_rate"),
            source_line_id=line.get("source_line_id"),
            narration=line.get("narration"),
        ))

    return ledger


def reverse_posting(source_type, source_id, user_id=None, remarks=None):
    """
    Create a reversal entry (all Dr/Cr swapped) for the document's ACTIVE
    posting and flag that original is_reversed=True. Ledger rows are never
    deleted — the original and its reversal both stay and net to zero.

    The reversal is dated on the original posting date, so the period's
    figures come out right; callers must refuse when that FY is locked.

    Returns the reversal AccountingLedger, or None if nothing is active.
    SELECT FOR UPDATE on the original prevents a double reversal.
    Caller commits.
    """
    original = active_posting(source_type, source_id, for_update=True)
    if not original:
        return None

    cycle = AccountingLedger.query.filter_by(
        source_type=source_type,
        source_id=source_id,
        is_reversal=True,
    ).count() + 1
    suffix = "-REV" if cycle == 1 else f"-REV{cycle}"

    reversal = AccountingLedger(
        posting_date=original.posting_date,
        financial_year_id=original.financial_year_id,
        source_type=source_type,
        source_id=source_id,
        voucher_no=original.voucher_no + suffix,
        project_code=original.project_code,
        remarks=remarks or f"Reversal of {original.voucher_no}",
        is_reversal=True,
        reversed_posting_id=original.id,
        total_debit=original.total_credit,
        total_credit=original.total_debit,
        created_by=user_id,
    )
    db.session.add(reversal)
    original.is_reversed = True
    db.session.flush()

    for line in original.lines:
        swapped = "Cr" if line.dr_cr == "Dr" else "Dr"
        db.session.add(AccountingLedgerLine(
            posting_id=reversal.id,
            sl_no=line.sl_no,
            account_type=line.account_type,
            cc_id=line.cc_id,
            vendor_id=line.vendor_id,
            bank_cash_id=line.bank_cash_id,
            dr_cr=swapped,
            amount=line.amount,
            project_code=line.project_code,
            cost_centre_code=line.cost_centre_code,
            gst_type=line.gst_type,
            gst_rate=line.gst_rate,
            source_line_id=line.source_line_id,
            narration=f"Reversal: {line.narration or ''}",
        ))

    return reversal


def fix_gst_ledger_lines():
    """
    One-time fix: update existing AccountingLedgerLine rows that have gst_type
    so their cc_id points to the dedicated GST CC codes instead of the
    expense/revenue CC that was incorrectly stored.

    Returns dict with counts of fixed lines.
    """
    from app.models.cc_code import CCCode
    from .posting_rules import _resolve_gst_cc

    _INPUT_TYPES  = {"purchase_bill", "payment_voucher", "debit_note", "petty_cash_docket"}
    _OUTPUT_TYPES = {"sale_bill", "credit_note", "sale_receipt_billing"}

    rows = (
        db.session.query(AccountingLedgerLine, AccountingLedger.source_type)
        .join(AccountingLedger, AccountingLedgerLine.posting_id == AccountingLedger.id)
        .filter(AccountingLedgerLine.gst_type.isnot(None))
        .all()
    )

    cc_code_cache = {}

    fixed = 0
    skipped = 0
    for line, source_type in rows:
        if source_type in _INPUT_TYPES:
            direction = "Input"
        elif source_type in _OUTPUT_TYPES:
            direction = "Output"
        else:
            skipped += 1
            continue

        correct_cc_code = _resolve_gst_cc(direction, line.gst_type)
        if not correct_cc_code:
            skipped += 1
            continue

        if correct_cc_code not in cc_code_cache:
            cc = CCCode.query.filter_by(cc_code=correct_cc_code).first()
            cc_code_cache[correct_cc_code] = cc

        cc = cc_code_cache[correct_cc_code]
        if not cc:
            skipped += 1
            continue

        if cc.id != line.cc_id:
            line.cc_id = cc.id
            line.cost_centre_code = cc.cc_code
            fixed += 1

    db.session.commit()
    return {"fixed": fixed, "skipped": skipped, "total": len(rows)}
