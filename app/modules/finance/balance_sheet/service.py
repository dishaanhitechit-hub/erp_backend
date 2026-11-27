from app.modules.finance.accounting.ledger_service import get_balance_sheet_report


def get_balance_sheet(params):
    return get_balance_sheet_report(params)
