from flask import Blueprint, request
from app.middleware.auth_middleware import login_required
from app.modules.finance.petty_cash.ledger.service import (
    get_petty_cash_ledger_list,
    get_petty_cash_ledger_detail,
)

petty_cash_ledger_bp = Blueprint("petty_cash_ledger", __name__)


# ── 1. LIST — budget summary cards ───────────────────────────────
@petty_cash_ledger_bp.route("/list", methods=["GET"])
@login_required
def api_petty_cash_ledger_list():
    return get_petty_cash_ledger_list(request.args.to_dict())


# ── 2. DETAIL — full ledger for one budget ────────────────────────
@petty_cash_ledger_bp.route("/budget/<int:budget_id>", methods=["GET"])
@login_required
def api_petty_cash_ledger_detail(budget_id):
    return get_petty_cash_ledger_detail(budget_id)
