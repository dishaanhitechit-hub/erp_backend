from flask import Blueprint, request
from app.middleware.auth_middleware import login_required
from app.modules.finance.petty_cash.ledger.service import (
    get_project_linked_accounts,
    get_petty_cash_account_ledger,
)

petty_cash_ledger_bp = Blueprint("petty_cash_ledger", __name__)


# ── 1. PROJECT LINKED ACCOUNTS ────────────────────────────────────
@petty_cash_ledger_bp.route("/project-accounts", methods=["GET"])
@login_required
def api_project_linked_accounts():
    return get_project_linked_accounts(request.args.to_dict())


# ── 2. ACCOUNT LEDGER ─────────────────────────────────────────────
@petty_cash_ledger_bp.route("/account-ledger", methods=["GET"])
@login_required
def api_petty_cash_account_ledger():
    return get_petty_cash_account_ledger(request.args.to_dict())
