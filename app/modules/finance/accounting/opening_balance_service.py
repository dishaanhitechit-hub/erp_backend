"""
Opening Balance Management.

Opening balances are stored as regular AccountingLedger postings with
source_type = "opening_balance". Each entry has exactly two lines:
one Dr and one Cr — the contra is always the "Opening Balance Equity"
CC code (OBE).

This allows opening balances to flow naturally through the General Ledger,
Trial Balance, P&L and Balance Sheet without special handling.
"""

from decimal import Decimal
from datetime import date as _date

from app.extensions import db
from app.models.accounting import AccountingLedger, AccountingLedgerLine, FinancialYear
from app.models.cc_code import CCCode
from app.models.vendor import Vendor
from app.models.bankCash import BankCash


def _resolve_fy(posting_date):
    fy = FinancialYear.query.filter(
        FinancialYear.start_date <= posting_date,
        FinancialYear.end_date >= posting_date,
    ).first()
    return fy.id if fy else None


def _parse_date(s):
    if not s:
        return None
    try:
        return _date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _account_name(account_type, account_id):
    if account_type == "CC":
        cc = CCCode.query.get(account_id)
        return f"{cc.cc_code} - {cc.cc_name}" if cc else str(account_id)
    elif account_type == "Vendor":
        v = Vendor.query.get(account_id)
        return f"{v.ledger_code} - {v.ledger_name}" if v else str(account_id)
    elif account_type == "BankCash":
        bc = BankCash.query.get(account_id)
        return f"{bc.bank_code} - {bc.bank_name}" if bc else str(account_id)
    return str(account_id)


def _resolve_obe_cc_id():
    cc = CCCode.query.filter(CCCode.cc_code == "OBE").first()
    return cc.id if cc else None


def list_opening_balances(params):
    fy_id = params.get("financial_year_id")
    project_code = params.get("project_code")

    reversed_ids = db.session.query(AccountingLedger.reversed_posting_id).filter(
        AccountingLedger.source_type == "opening_balance",
        AccountingLedger.is_reversal == True,
        AccountingLedger.reversed_posting_id.isnot(None),
    )

    q = AccountingLedger.query.filter_by(source_type="opening_balance", is_reversal=False)
    q = q.filter(~AccountingLedger.id.in_(reversed_ids))
    if fy_id:
        q = q.filter_by(financial_year_id=int(fy_id))
    if project_code:
        q = q.filter_by(project_code=project_code)
    q = q.order_by(AccountingLedger.posting_date, AccountingLedger.id)

    results = []
    for posting in q.all():
        main_line = None
        for line in posting.lines:
            obe_cc = CCCode.query.filter(CCCode.cc_code == "OBE").first()
            if obe_cc and line.cc_id == obe_cc.id and line.account_type == "CC":
                continue
            main_line = line
            break

        if not main_line:
            main_line = posting.lines[0] if posting.lines else None

        account_id = None
        if main_line:
            account_id = main_line.cc_id or main_line.vendor_id or main_line.bank_cash_id

        results.append({
            "id": posting.id,
            "postingDate": posting.posting_date.isoformat() if posting.posting_date else None,
            "financialYearId": posting.financial_year_id,
            "fyCode": posting.financial_year.fy_code if posting.financial_year else None,
            "projectCode": posting.project_code,
            "accountType": main_line.account_type if main_line else None,
            "accountId": account_id,
            "accountName": _account_name(main_line.account_type, account_id) if main_line and account_id else "—",
            "drCr": main_line.dr_cr if main_line else None,
            "amount": float(main_line.amount) if main_line else 0,
            "narration": posting.remarks,
            "createdAt": posting.created_at.isoformat() if posting.created_at else None,
        })

    return {"message": "OK", "data": results}, 200


def save_opening_balance(payload, user_id):
    if not payload:
        return {"message": "No data provided"}, 400

    account_type = payload.get("account_type")
    account_id = payload.get("account_id")
    dr_cr = payload.get("dr_cr")
    amount_raw = payload.get("amount")
    fy_id = payload.get("financial_year_id")
    project_code = payload.get("project_code")
    narration = payload.get("narration", "")

    if not account_type or not account_id or not dr_cr or not amount_raw:
        return {"message": "account_type, account_id, dr_cr and amount required"}, 400

    if dr_cr not in ("Dr", "Cr"):
        return {"message": "dr_cr must be 'Dr' or 'Cr'"}, 400

    amount = Decimal(str(amount_raw))
    if amount <= 0:
        return {"message": "Amount must be positive"}, 400

    if not fy_id:
        return {"message": "financial_year_id required"}, 400

    fy = FinancialYear.query.get(int(fy_id))
    if not fy:
        return {"message": "Financial year not found"}, 404
    if fy.is_locked:
        return {"message": "Financial year is locked"}, 400

    posting_date = fy.start_date

    existing = AccountingLedger.query.filter_by(
        source_type="opening_balance",
        is_reversal=False,
        financial_year_id=int(fy_id),
    ).filter(
        ~AccountingLedger.id.in_(
            db.session.query(AccountingLedger.reversed_posting_id).filter(
                AccountingLedger.source_type == "opening_balance",
                AccountingLedger.is_reversal == True,
                AccountingLedger.reversed_posting_id.isnot(None),
            )
        )
    ).join(AccountingLedgerLine).filter(
        AccountingLedgerLine.account_type == account_type,
    )

    if account_type == "CC":
        existing = existing.filter(AccountingLedgerLine.cc_id == int(account_id))
    elif account_type == "Vendor":
        existing = existing.filter(AccountingLedgerLine.vendor_id == int(account_id))
    elif account_type == "BankCash":
        existing = existing.filter(AccountingLedgerLine.bank_cash_id == int(account_id))

    if project_code:
        existing = existing.filter(AccountingLedger.project_code == project_code)

    if existing.first():
        return {
            "message": "Opening balance already exists for this account/FY/project. Delete the existing one first."
        }, 409

    obe_cc_id = _resolve_obe_cc_id()

    voucher_no = f"OB-{fy.fy_code}-{account_type[:2]}{account_id}"
    if project_code:
        voucher_no += f"-{project_code}"

    ledger = AccountingLedger(
        posting_date=posting_date,
        financial_year_id=int(fy_id),
        source_type="opening_balance",
        source_id=0,
        voucher_no=voucher_no,
        project_code=project_code or None,
        remarks=narration or f"Opening balance: {account_type} {account_id}",
        is_reversal=False,
        total_debit=amount,
        total_credit=amount,
        created_by=user_id,
    )
    db.session.add(ledger)
    db.session.flush()

    main_line_kwargs = {
        "posting_id": ledger.id,
        "sl_no": 1,
        "account_type": account_type,
        "dr_cr": dr_cr,
        "amount": amount,
        "project_code": project_code,
        "narration": narration,
    }
    if account_type == "CC":
        main_line_kwargs["cc_id"] = int(account_id)
    elif account_type == "Vendor":
        main_line_kwargs["vendor_id"] = int(account_id)
    elif account_type == "BankCash":
        main_line_kwargs["bank_cash_id"] = int(account_id)

    db.session.add(AccountingLedgerLine(**main_line_kwargs))

    contra_dr_cr = "Cr" if dr_cr == "Dr" else "Dr"
    db.session.add(AccountingLedgerLine(
        posting_id=ledger.id,
        sl_no=2,
        account_type="CC",
        cc_id=obe_cc_id,
        dr_cr=contra_dr_cr,
        amount=amount,
        project_code=project_code,
        narration="Opening Balance Equity contra",
    ))

    db.session.commit()

    return {
        "message": "Opening balance saved",
        "data": {"id": ledger.id, "voucherNo": voucher_no},
    }, 201


def delete_opening_balance(posting_id, user_id):
    posting = AccountingLedger.query.get(posting_id)
    if not posting:
        return {"message": "Not found"}, 404

    if posting.source_type != "opening_balance":
        return {"message": "Only opening balance entries can be deleted here"}, 400

    if posting.financial_year and posting.financial_year.is_locked:
        return {"message": "Financial year is locked"}, 400

    already_reversed = AccountingLedger.query.filter_by(
        source_type="opening_balance",
        source_id=posting.source_id,
        is_reversal=True,
        reversed_posting_id=posting.id,
    ).first()
    if already_reversed:
        return {"message": "This opening balance has already been reversed"}, 409

    reversal = AccountingLedger(
        posting_date=posting.posting_date,
        financial_year_id=posting.financial_year_id,
        source_type="opening_balance",
        source_id=posting.source_id,
        voucher_no=f"{posting.voucher_no}-REV",
        project_code=posting.project_code,
        remarks=f"Reversal of {posting.voucher_no}",
        is_reversal=True,
        reversed_posting_id=posting.id,
        total_debit=posting.total_debit,
        total_credit=posting.total_credit,
        created_by=user_id,
    )
    db.session.add(reversal)
    db.session.flush()

    for line in posting.lines:
        rev_dr_cr = "Cr" if line.dr_cr == "Dr" else "Dr"
        db.session.add(AccountingLedgerLine(
            posting_id=reversal.id,
            sl_no=line.sl_no,
            account_type=line.account_type,
            cc_id=line.cc_id,
            vendor_id=line.vendor_id,
            bank_cash_id=line.bank_cash_id,
            dr_cr=rev_dr_cr,
            amount=line.amount,
            project_code=line.project_code,
            cost_centre_code=line.cost_centre_code,
            gst_type=line.gst_type,
            gst_rate=line.gst_rate,
            narration=f"Reversal: {line.narration or ''}",
        ))

    db.session.commit()
    return {
        "message": "Opening balance reversed successfully",
        "data": {"reversalId": reversal.id, "reversalVoucherNo": reversal.voucher_no},
    }, 200
