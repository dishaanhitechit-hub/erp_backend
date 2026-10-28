from datetime import datetime
from app.extensions import db
from app.response import res

from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.bankCash import BankCash
from app.models.saleBill import SaleBillMaster, SaleBillGst
from app.models.saleReceipt import SaleReceiptMaster
from app.models.purchaseVoucher import PurchaseVoucherMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster, BillPaymentReceiptGst
from app.models.cc_code import CCCode
from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher, PettyCashDocketVoucherDetail


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────
# AGGREGATION HELPERS
# ──────────────────────────────────────────────────────────────

def _journal_balance(cc_codes, project_code=None, from_date=None, to_date=None):
    """
    Net balance from approved JournalEntryLine for the given cc_codes.
    Returns credit_amount - debit_amount  (positive = credit-heavy = liability/equity)
    """
    if not cc_codes:
        return 0.0
    codes_upper = [c.upper() for c in cc_codes]
    q = (
        db.session.query(
            db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0).label("cr"),
            db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount),  0).label("dr"),
        )
        .join(CCCode, JournalEntryLine.cc_id == CCCode.id)
        .join(JournalEntryMaster, JournalEntryLine.journal_id == JournalEntryMaster.id)
        .filter(
            db.func.upper(CCCode.cc_code).in_(codes_upper),
            JournalEntryMaster.workflow_status == "Approved",
            JournalEntryMaster.status == "Active",
        )
    )
    if project_code:
        q = q.filter(JournalEntryMaster.project_code == project_code)
    if from_date:
        q = q.filter(JournalEntryMaster.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntryMaster.entry_date <= to_date)
    row = q.one()
    return float(row.cr or 0) - float(row.dr or 0)


def _journal_debit_sum(cc_codes, project_code=None, from_date=None, to_date=None):
    """Sum of debit amounts only — used for asset-side codes."""
    if not cc_codes:
        return 0.0
    codes_upper = [c.upper() for c in cc_codes]
    q = (
        db.session.query(
            db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0)
        )
        .join(CCCode, JournalEntryLine.cc_id == CCCode.id)
        .join(JournalEntryMaster, JournalEntryLine.journal_id == JournalEntryMaster.id)
        .filter(
            db.func.upper(CCCode.cc_code).in_(codes_upper),
            JournalEntryMaster.workflow_status == "Approved",
            JournalEntryMaster.status == "Active",
        )
    )
    if project_code:
        q = q.filter(JournalEntryMaster.project_code == project_code)
    if from_date:
        q = q.filter(JournalEntryMaster.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntryMaster.entry_date <= to_date)
    return float(q.scalar() or 0)


def _bulk_journal_balance(cc_codes, project_code=None, from_date=None, to_date=None):
    """Net balance (credit − debit) for many cc_codes in ONE grouped query."""
    if not cc_codes:
        return {}
    codes_upper = [c.upper() for c in cc_codes]
    q = (
        db.session.query(
            db.func.upper(CCCode.cc_code).label("code"),
            db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0).label("cr"),
            db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount),  0).label("dr"),
        )
        .join(CCCode, JournalEntryLine.cc_id == CCCode.id)
        .join(JournalEntryMaster, JournalEntryLine.journal_id == JournalEntryMaster.id)
        .filter(
            db.func.upper(CCCode.cc_code).in_(codes_upper),
            JournalEntryMaster.workflow_status == "Approved",
            JournalEntryMaster.status == "Active",
        )
        .group_by(db.func.upper(CCCode.cc_code))
    )
    if project_code:
        q = q.filter(JournalEntryMaster.project_code == project_code)
    if from_date:
        q = q.filter(JournalEntryMaster.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntryMaster.entry_date <= to_date)
    result = {c: 0.0 for c in codes_upper}
    for row in q.all():
        result[row.code] = float(row.cr or 0) - float(row.dr or 0)
    return result


def _bulk_journal_debit_sum(cc_codes, project_code=None, from_date=None, to_date=None):
    """Debit sum for many cc_codes in ONE grouped query."""
    if not cc_codes:
        return {}
    codes_upper = [c.upper() for c in cc_codes]
    q = (
        db.session.query(
            db.func.upper(CCCode.cc_code).label("code"),
            db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0).label("dr"),
        )
        .join(CCCode, JournalEntryLine.cc_id == CCCode.id)
        .join(JournalEntryMaster, JournalEntryLine.journal_id == JournalEntryMaster.id)
        .filter(
            db.func.upper(CCCode.cc_code).in_(codes_upper),
            JournalEntryMaster.workflow_status == "Approved",
            JournalEntryMaster.status == "Active",
        )
        .group_by(db.func.upper(CCCode.cc_code))
    )
    if project_code:
        q = q.filter(JournalEntryMaster.project_code == project_code)
    if from_date:
        q = q.filter(JournalEntryMaster.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntryMaster.entry_date <= to_date)
    result = {c: 0.0 for c in codes_upper}
    for row in q.all():
        result[row.code] = float(row.dr or 0)
    return result


def _bank_balance_by_code(bank_code):
    """
    Closing balance for a specific BankCash account by its bank_code.
    opening_balance + total credits received - total debits paid.
    Since we don't store a running balance on BankCash, we sum from JournalEntryLine
    where the journal's bank_ac_id matches this account.
    Falls back to zero when not tracked via journal entries.
    """
    bank = BankCash.query.filter_by(bank_code=bank_code, status="Active").first()
    if not bank:
        return 0.0, None
    # Closing = sum of all credits into this bank minus debits out via approved journal entries
    # We'll aggregate from PaymentVoucherMaster and BillPaymentReceiptMaster amounts
    from app.models.paymentVoucher import PaymentVoucherMaster
    paid_out = db.session.query(
        db.func.coalesce(db.func.sum(PaymentVoucherMaster.total_invoice_amount), 0)
    ).filter(
        PaymentVoucherMaster.bank_ac_id == bank.id,
        PaymentVoucherMaster.payment_mode == "Bank",
        PaymentVoucherMaster.workflow_status == "Approved",
        PaymentVoucherMaster.status == "Active",
    ).scalar()
    received_in = db.session.query(
        db.func.coalesce(db.func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0)
    ).filter(
        BillPaymentReceiptMaster.bank_ac_id == bank.id,
        BillPaymentReceiptMaster.payment_mode == "Bank",
        BillPaymentReceiptMaster.workflow_status == "Approved",
        BillPaymentReceiptMaster.status == "Active",
    ).scalar()
    balance = float(received_in or 0) - float(paid_out or 0)
    return balance, bank.bank_name or bank.bank_code


def _all_bank_balances(project_code=None, from_date=None, to_date=None):
    """Return list of {code, name, balance} for every active BankCash bank account."""
    from app.models.paymentVoucher import PaymentVoucherMaster
    banks = BankCash.query.filter_by(type="Bank", status="Active").all()
    if not banks:
        return []
    bank_ids = [b.id for b in banks]

    # One grouped query for all paid-out amounts
    q_out = (
        db.session.query(
            PaymentVoucherMaster.bank_ac_id,
            db.func.coalesce(db.func.sum(PaymentVoucherMaster.total_invoice_amount), 0).label("total"),
        )
        .filter(
            PaymentVoucherMaster.bank_ac_id.in_(bank_ids),
            PaymentVoucherMaster.payment_mode == "Bank",
            PaymentVoucherMaster.workflow_status == "Approved",
            PaymentVoucherMaster.status == "Active",
        )
        .group_by(PaymentVoucherMaster.bank_ac_id)
    )
    if project_code:
        q_out = q_out.filter(PaymentVoucherMaster.project_code == project_code)
    if from_date:
        q_out = q_out.filter(PaymentVoucherMaster.payment_date >= from_date)
    if to_date:
        q_out = q_out.filter(PaymentVoucherMaster.payment_date <= to_date)
    out_map = {row.bank_ac_id: float(row.total or 0) for row in q_out.all()}

    # One grouped query for all received-in amounts
    q_in = (
        db.session.query(
            BillPaymentReceiptMaster.bank_ac_id,
            db.func.coalesce(db.func.sum(BillPaymentReceiptMaster.total_invoice_amount), 0).label("total"),
        )
        .filter(
            BillPaymentReceiptMaster.bank_ac_id.in_(bank_ids),
            BillPaymentReceiptMaster.payment_mode == "Bank",
            BillPaymentReceiptMaster.workflow_status == "Approved",
            BillPaymentReceiptMaster.status == "Active",
        )
        .group_by(BillPaymentReceiptMaster.bank_ac_id)
    )
    if project_code:
        q_in = q_in.filter(BillPaymentReceiptMaster.project_code == project_code)
    if from_date:
        q_in = q_in.filter(BillPaymentReceiptMaster.payment_date >= from_date)
    if to_date:
        q_in = q_in.filter(BillPaymentReceiptMaster.payment_date <= to_date)
    in_map = {row.bank_ac_id: float(row.total or 0) for row in q_in.all()}

    return [
        {
            "code":    b.bank_code,
            "name":    b.bank_name or b.bank_code,
            "balance": in_map.get(b.id, 0.0) - out_map.get(b.id, 0.0),
        }
        for b in banks
    ]


def _cash_balance(project_code=None, from_date=None, to_date=None):
    """
    Cash in hand = sum of approved petty cash docket voucher totals (Cash mode).
    """
    q = db.session.query(
        db.func.coalesce(db.func.sum(PettyCashDocketVoucher.total_amount), 0)
    ).filter(
        PettyCashDocketVoucher.mode_of_payment == "Cash",
        PettyCashDocketVoucher.workflow_status == "Approved",
    )
    if project_code:
        q = q.filter(PettyCashDocketVoucher.project_code == project_code)
    if from_date:
        q = q.filter(PettyCashDocketVoucher.voucher_date >= from_date)
    if to_date:
        q = q.filter(PettyCashDocketVoucher.voucher_date <= to_date)
    return float(q.scalar() or 0)


def _gst_output_net(project_code=None, from_date=None, to_date=None):
    """
    GST Payable = Output GST (sale bills) - Input GST (purchase bill receipts)
    Returns dict with per-type breakdown and net.
    """
    # Output GST from sale bills
    sq = db.session.query(
        SaleBillGst.gst_type,
        db.func.coalesce(db.func.sum(SaleBillGst.gst_amount), 0).label("amt"),
    ).join(SaleBillMaster, SaleBillGst.sale_bill_id == SaleBillMaster.id).filter(
        SaleBillGst.is_selected == True,
        SaleBillMaster.workflow_status == "Approved",
        SaleBillMaster.status == "Active",
    )
    if project_code:
        sq = sq.filter(SaleBillMaster.project_code == project_code)
    if from_date:
        sq = sq.filter(SaleBillMaster.invoice_date >= from_date)
    if to_date:
        sq = sq.filter(SaleBillMaster.invoice_date <= to_date)
    output_rows = sq.group_by(SaleBillGst.gst_type).all()
    output_map = {r.gst_type.upper(): float(r.amt or 0) for r in output_rows}

    # Input GST from purchase bill payment receipts (current_amount = GST paid)
    pq = db.session.query(
        BillPaymentReceiptGst.gst_type,
        db.func.coalesce(db.func.sum(BillPaymentReceiptGst.current_amount), 0).label("amt"),
    ).join(BillPaymentReceiptMaster, BillPaymentReceiptGst.receipt_id == BillPaymentReceiptMaster.id).filter(
        BillPaymentReceiptMaster.workflow_status == "Approved",
        BillPaymentReceiptMaster.status == "Active",
    )
    if project_code:
        pq = pq.filter(BillPaymentReceiptMaster.project_code == project_code)
    if from_date:
        pq = pq.filter(BillPaymentReceiptMaster.payment_date >= from_date)
    if to_date:
        pq = pq.filter(BillPaymentReceiptMaster.payment_date <= to_date)
    input_rows = pq.group_by(BillPaymentReceiptGst.gst_type).all()
    input_map = {r.gst_type.upper(): float(r.amt or 0) for r in input_rows}

    igst_out  = output_map.get("IGST", 0)
    cgst_out  = output_map.get("CGST", 0)
    sgst_out  = output_map.get("SGST", 0)
    igst_in   = input_map.get("IGST", 0)
    cgst_in   = input_map.get("CGST", 0)
    sgst_in   = input_map.get("SGST", 0)
    net_gst   = (igst_out + cgst_out + sgst_out) - (igst_in + cgst_in + sgst_in)

    return {
        "igst_output": igst_out,
        "cgst_output": cgst_out,
        "sgst_output": sgst_out,
        "igst_input":  igst_in,
        "cgst_input":  cgst_in,
        "sgst_input":  sgst_in,
        "net_gst_payable": net_gst,
    }


def _sundry_debtors(project_code=None, from_date=None, to_date=None):
    """
    CASD = approved sale bill totals - sale receipt totals
    SaleReceiptMaster has no workflow_status; all records count.
    """
    bq = db.session.query(
        db.func.coalesce(db.func.sum(SaleBillMaster.total_invoice_amount), 0)
    ).filter(
        SaleBillMaster.workflow_status == "Approved",
        SaleBillMaster.status == "Active",
    )
    if project_code:
        bq = bq.filter(SaleBillMaster.project_code == project_code)
    if from_date:
        bq = bq.filter(SaleBillMaster.invoice_date >= from_date)
    if to_date:
        bq = bq.filter(SaleBillMaster.invoice_date <= to_date)

    rq = db.session.query(
        db.func.coalesce(db.func.sum(SaleReceiptMaster.total_amount), 0)
    )
    if project_code:
        rq = rq.filter(SaleReceiptMaster.project_code == project_code)
    if from_date:
        rq = rq.filter(SaleReceiptMaster.entry_date >= from_date)
    if to_date:
        rq = rq.filter(SaleReceiptMaster.entry_date <= to_date)

    return float(bq.scalar() or 0) - float(rq.scalar() or 0)


def _advance_to_vendors(project_code=None, from_date=None, to_date=None):
    """
    CAAV = sum of advance payments from approved purchase vouchers
    (total_invoice_amount paid out to vendors).
    """
    q = db.session.query(
        db.func.coalesce(db.func.sum(PurchaseVoucherMaster.total_invoice_amount), 0)
    ).filter(
        PurchaseVoucherMaster.workflow_status == "Approved",
        PurchaseVoucherMaster.status == "Active",
    )
    if project_code:
        q = q.filter(PurchaseVoucherMaster.project_code == project_code)
    if from_date:
        q = q.filter(PurchaseVoucherMaster.voucher_date >= from_date)
    if to_date:
        q = q.filter(PurchaseVoucherMaster.voucher_date <= to_date)
    return float(q.scalar() or 0)


def _grn_value(project_code=None, from_date=None, to_date=None):
    """
    CARM = raw materials stock value tracked via JournalEntry lines
    tagged with the CARM cc_code (debit side = received inventory).
    """
    return _journal_debit_sum(["CARM"], project_code=project_code,
                              from_date=from_date, to_date=to_date)


def _pl_net(project_code=None, from_date=None, to_date=None):
    """
    CRSF = P&L net (income - expense).
    Reuses same logic as profit_loss service but returns a single net number.
    """
    from app.models.ogSaleOrder import OgSaleOrderMaster
    from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode

    so_q = OgSaleOrderMaster.query.filter(
        OgSaleOrderMaster.workflow_status == "Approved",
        OgSaleOrderMaster.status == "Active",
    )
    if project_code:
        so_q = so_q.filter(OgSaleOrderMaster.project_code == project_code)
    if from_date:
        so_q = so_q.filter(OgSaleOrderMaster.og_sale_order_date >= from_date)
    if to_date:
        so_q = so_q.filter(OgSaleOrderMaster.og_sale_order_date <= to_date)
    income = float(so_q.with_entities(
        db.func.coalesce(db.func.sum(OgSaleOrderMaster.total_amount), 0)
    ).scalar() or 0)

    # Direct Expenses — sum of all DE sibling cc_total from BudgetItemCCCode
    cc_q = (
        db.session.query(
            db.func.coalesce(db.func.sum(BudgetItemCCCode.cc_total), 0)
        )
        .join(BudgetItem,   BudgetItemCCCode.budget_item_id == BudgetItem.id)
        .join(BudgetMaster, BudgetItem.budget_id            == BudgetMaster.id)
        .filter(
            BudgetMaster.workflow_status == "Approved",
            BudgetMaster.status          == "Active",
        )
    )
    if project_code:
        cc_q = cc_q.filter(BudgetMaster.project_code == project_code)
    if from_date:
        cc_q = cc_q.filter(BudgetMaster.budget_date >= from_date)
    if to_date:
        cc_q = cc_q.filter(BudgetMaster.budget_date <= to_date)
    direct_expense = float(cc_q.scalar() or 0)

    # Overhead — estimated costs from BudgetMaster.overhead_data JSON column
    bm_q = BudgetMaster.query.filter(
        BudgetMaster.workflow_status == "Approved",
        BudgetMaster.status          == "Active",
    )
    if project_code:
        bm_q = bm_q.filter(BudgetMaster.project_code == project_code)
    if from_date:
        bm_q = bm_q.filter(BudgetMaster.budget_date >= from_date)
    if to_date:
        bm_q = bm_q.filter(BudgetMaster.budget_date <= to_date)

    overhead_total = 0.0
    for (od,) in bm_q.with_entities(BudgetMaster.overhead_data).all():
        if od:
            for entry in od.get("projectOverhead", []) + od.get("employeeOverhead", []):
                overhead_total += float(entry.get("estimatedCost") or 0)

    # TEC = Direct Expenses + Overhead; P&L net = Income − TEC
    expense = direct_expense + overhead_total
    return income - expense


# ──────────────────────────────────────────────────────────────
# MAIN SERVICE
# ──────────────────────────────────────────────────────────────

def get_balance_sheet(args):
    try:
        project_code = args.get("projectCode")
        from_date    = _parse_date(args.get("fromDate"))
        to_date      = _parse_date(args.get("toDate"))

        kw = dict(project_code=project_code, from_date=from_date, to_date=to_date)

        # ── SPECIAL COMPUTATIONS ────────────────────────────────

        pl_net = _pl_net(**kw)
        gst    = _gst_output_net(**kw)
        banks  = _all_bank_balances(**kw)
        cash   = _cash_balance(**kw)
        casd   = _sundry_debtors(**kw)
        caav   = _advance_to_vendors(**kw)

        bank_total = sum(b["balance"] for b in banks)

        # Two bulk queries replace ~30 individual _journal_balance / _journal_debit_sum calls
        jb = _bulk_journal_balance(
            ["DIR1", "DIR2", "LON3", "LON1", "LON2", "USLO", "NBFC",
             "NCDT", "NCTL", "NCTP",
             "CLDT", "CLSC", "CLTB", "CLTP", "CLFP", "CLCP", "CLOP", "CLCM"],
            **kw,
        )
        jd = _bulk_journal_debit_sum(
            ["CARM", "CAHL", "CAAP", "CAUM", "CAWP", "CART", "CAAE", "CAOP",
             "CACI", "CATS", "CAOA",
             "APNM", "ASRV", "AOFG", "AELE", "AMEG", "ALGH",
             "AINF", "ASCF", "ASHT", "AEIT", "AETT", "ACAB",
             "NCIV", "NCTA", "LTLA", "NCCA"],
            **kw,
        )

        # ── EQUITY & LIABILITIES ────────────────────────────────

        dir1 = jb["DIR1"]
        dir2 = jb["DIR2"]
        shareholders_fund = dir1 + dir2
        crsf = pl_net
        capital_total = shareholders_fund + crsf

        # Non-current liabilities
        lon3_kotak_jcb     = jb["LON3"]
        lon3_kotak_venus   = 0.0  # same code, separate tracking via journal remarks — not distinguishable without sub-code
        lon1_bajaj         = jb["LON1"]
        lon2_lt            = jb["LON2"]
        lon3_icici_od      = 0.0  # LON3 shared; split tracked separately
        uslo               = jb["USLO"]
        nbfc               = jb["NBFC"]

        secured_banking     = lon3_kotak_jcb + lon3_kotak_venus
        secured_nonbanking  = lon1_bajaj + lon2_lt
        unsecured_banking   = lon3_icici_od + uslo
        unsecured_nonbanking = nbfc
        nctb_total = secured_banking + secured_nonbanking + unsecured_banking + unsecured_nonbanking

        ncdt = jb["NCDT"]
        nctl = jb["NCTL"]
        nctp = jb["NCTP"]
        non_current_liability_total = nctb_total + ncdt + nctl + nctp

        # Current liabilities
        cldt = jb["CLDT"]
        clsc = jb["CLSC"]
        cltb = jb["CLTB"]
        cltp = jb["CLTP"]
        clfp = jb["CLFP"]
        clcp = jb["CLCP"]
        clop = jb["CLOP"]
        clcm = jb["CLCM"]
        clot_total = clfp + clcp + clop + clcm
        clgp = gst["net_gst_payable"]
        current_liability_total = cldt + clsc + cltb + cltp + clot_total + clgp

        total_equity_liability = capital_total + non_current_liability_total + current_liability_total

        # ── ASSETS ──────────────────────────────────────────────

        # Fixed assets (Non-current)
        asset_codes = ["APNM", "ASRV", "AOFG", "AELE", "AMEG", "ALGH",
                       "AINF", "ASCF", "ASHT", "AEIT", "AETT", "ACAB"]
        fixed_assets_map = {code: jd[code] for code in asset_codes}
        fixed_assets_total = sum(fixed_assets_map.values())

        nciv = jd["NCIV"]
        ncta = jd["NCTA"]
        ltla = jd["LTLA"]
        ncca = jd["NCCA"]
        non_current_assets_total = fixed_assets_total + nciv + ncta + ltla + ncca

        # Current assets
        carm = jd["CARM"]   # CARM = GRN value (raw materials received)
        cahl = jd["CAHL"]
        caap = jd["CAAP"]
        caum = jd["CAUM"]
        cawp = jd["CAWP"]
        cacs_total = carm + cahl + caap + caum + cawp

        cart = jd["CART"]

        caae = jd["CAAE"]
        caop = jd["CAOP"]
        cala_total = caav + caae + caop

        caci = jd["CACI"]
        cats = jd["CATS"]
        caoa = jd["CAOA"]

        gst_excess_input = max(0.0, -gst["net_gst_payable"])  # when input > output

        current_assets_total = (
            cacs_total + casd + cart + cala_total
            + caci + cats + caoa + gst_excess_input
            + bank_total + cash
        )

        total_assets = non_current_assets_total + current_assets_total

        # ── BUILD RESPONSE ──────────────────────────────────────

        equity_and_liabilities = {
            "A_capitalAccount": {
                "label": "Capital account",
                "A1_shareholdersFund": {
                    "label": "Shareholder's fund",
                    "items": [
                        {"code": "DIR1", "label": "Director 1 capital",  "value": dir1},
                        {"code": "DIR2", "label": "Director 2 capital",  "value": dir2},
                    ],
                    "total": shareholders_fund,
                },
                "A2_CRSF": {
                    "code":  "CRSF",
                    "label": "Company reserves & surplus fund (P&L)",
                    "value": crsf,
                },
                "total": capital_total,
            },
            "B_nonCurrentLiability": {
                "label": "Non-current liability",
                "B1_NCTB": {
                    "code":  "NCTB",
                    "label": "Long-term borrowings",
                    "B1_1_securedBanking": {
                        "label": "Secured loan — banking (SLON)",
                        "items": [
                            {"code": "LON3", "label": "Kotak Mahindra Bank — JCB",   "value": lon3_kotak_jcb},
                            {"code": "LON3", "label": "Kotak Mahindra Bank — Venus", "value": lon3_kotak_venus},
                        ],
                        "total": secured_banking,
                    },
                    "B1_2_securedNonBanking": {
                        "label": "Secured loan — non-banking",
                        "items": [
                            {"code": "LON1", "label": "Bajaj Finserv", "value": lon1_bajaj},
                            {"code": "LON2", "label": "L&T Finance",   "value": lon2_lt},
                        ],
                        "total": secured_nonbanking,
                    },
                    "B1_3_unsecuredBanking": {
                        "code":  "UNSL",
                        "label": "Unsecured loan — banking",
                        "items": [
                            {"code": "LON3", "label": "ICICI Bank OD A/c",              "value": lon3_icici_od},
                            {"code": "USLO", "label": "From director & relatives",       "value": uslo},
                        ],
                        "total": unsecured_banking,
                    },
                    "B1_4_unsecuredNonBanking": {
                        "label": "Unsecured loan — non-banking",
                        "items": [
                            {"code": "NBFC", "label": "NBFC", "value": nbfc},
                        ],
                        "total": unsecured_nonbanking,
                    },
                    "total": nctb_total,
                },
                "B2_NCDT": {"code": "NCDT", "label": "Deferred tax liabilities",    "value": ncdt},
                "B3_NCTL": {"code": "NCTL", "label": "Other long-term liabilities", "value": nctl},
                "B4_NCTP": {"code": "NCTP", "label": "Long-term provisions",        "value": nctp},
                "total": non_current_liability_total,
            },
            "C_currentLiabilities": {
                "label": "Current liabilities",
                "C1_CLDT": {"code": "CLDT", "label": "Duties & taxes",          "value": cldt},
                "C2_CLSC": {"code": "CLSC", "label": "Sundry creditors",        "value": clsc},
                "C3_CLTB": {"code": "CLTB", "label": "Short-term borrowings",   "value": cltb},
                "C4_CLTP": {"code": "CLTP", "label": "Short-term provisions",   "value": cltp},
                "C5_CLOT": {
                    "label": "Other current liabilities",
                    "items": [
                        {"code": "CLFP", "label": "Audit fees payable",              "value": clfp},
                        {"code": "CLCP", "label": "Consultancy fees payable",        "value": clcp},
                        {"code": "CLOP", "label": "Advance from others project",     "value": clop},
                        {"code": "CLCM", "label": "Consumable material received",    "value": clcm},
                    ],
                    "total": clot_total,
                },
                "C6_CLGP": {
                    "code":  "CLGP",
                    "label": "GST payable (output − input)",
                    "breakdown": {
                        "GST3_igst_output": gst["igst_output"],
                        "GST4_cgst_output": gst["cgst_output"],
                        "GST5_sgst_output": gst["sgst_output"],
                        "GST6_igst_input":  gst["igst_input"],
                        "GST7_cgst_input":  gst["cgst_input"],
                        "GST8_sgst_input":  gst["sgst_input"],
                    },
                    "value": clgp,
                },
                "total": current_liability_total,
            },
            "grandTotal": total_equity_liability,
        }

        assets = {
            "A_nonCurrentAssets": {
                "label": "Non-current assets",
                "A1_fixedAssets": {
                    "label": "Fixed assets",
                    "items": [
                        {"code": code, "value": val}
                        for code, val in fixed_assets_map.items()
                    ],
                    "total": fixed_assets_total,
                },
                "A2_NCIV": {"code": "NCIV", "label": "Non-current investment (security deposit)", "value": nciv},
                "A3_NCTA": {"code": "NCTA", "label": "Deferred tax assets",                       "value": ncta},
                "A4_LTLA": {"code": "LTLA", "label": "Long-term loans & advances (mob. advance)", "value": ltla},
                "A5_NCCA": {"code": "NCCA", "label": "Other non-current assets",                  "value": ncca},
                "total": non_current_assets_total,
            },
            "B_currentAssets": {
                "label": "Current assets",
                "B1_CACS": {
                    "code":  "CACS",
                    "label": "Closing stock",
                    "items": [
                        {"code": "CARM", "label": "Raw materials (GRN value)",          "value": carm},
                        {"code": "CAHL", "label": "Certified but hold",                 "value": cahl},
                        {"code": "CAAP", "label": "Certified amendment pending",        "value": caap},
                        {"code": "CAUM", "label": "Work done uncertified",              "value": caum},
                        {"code": "CAWP", "label": "Job work in progress",               "value": cawp},
                    ],
                    "total": cacs_total,
                },
                "B3_CASD": {"code": "CASD", "label": "Sundry debtors (sale − receipt)", "value": casd},
                "B8_CART": {"code": "CART", "label": "Retention on sale",               "value": cart},
                "B4_CALA": {
                    "code":  "CALA",
                    "label": "Short-term loans & advances",
                    "items": [
                        {"code": "CAAV", "label": "Advance to vendors",       "value": caav},
                        {"code": "CAAE", "label": "Advance to employees",     "value": caae},
                        {"code": "CAOP", "label": "Advance to other project", "value": caop},
                    ],
                    "total": cala_total,
                },
                "B5_CACI": {"code": "CACI", "label": "Current investment tax",  "value": caci},
                "B6_CATS": {"code": "CATS", "label": "TDS receivable",          "value": cats},
                "B7_CAOA": {"code": "CAOA", "label": "Other current assets",    "value": caoa},
                "B_gstExcessInput": {
                    "label": "GST excess input credit",
                    "value": gst_excess_input,
                },
                "B8_CABA": {
                    "code":  "CABA",
                    "label": "Bank accounts",
                    "accounts": banks,
                    "total": bank_total,
                },
                "B9_CACH": {
                    "code":  "CACH",
                    "label": "Cash in hand",
                    "value": cash,
                },
                "total": current_assets_total,
            },
            "grandTotal": total_assets,
        }

        difference = total_assets - total_equity_liability

        return res(
            "Balance sheet fetched",
            {
                "equityAndLiabilities": equity_and_liabilities,
                "assets":               assets,
                "difference":           round(difference, 2),
                "filters": {
                    "projectCode": project_code,
                    "fromDate":    str(from_date) if from_date else None,
                    "toDate":      str(to_date)   if to_date   else None,
                },
            },
            200,
        )

    except Exception as e:
        return res(str(e), [], 500)
