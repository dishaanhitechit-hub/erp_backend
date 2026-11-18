from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.bank_statement.service import (
    get_accounts,
    validate_statement,
    import_statement,
    list_batches,
    revert_batch,
    list_transactions,
    transaction_history,
    available_for_docket,
)

bank_statement_bp = Blueprint("bank_statement", __name__)


def _uid():
    return g.current_user.get("id") if hasattr(g, "current_user") else None


# BANK accounts the user may import / view statements for
@bank_statement_bp.route("/accounts", methods=["GET"])
@login_required
def api_bank_statement_accounts():
    return get_accounts(_uid())


# dry run: { bankAccountId, rows[] } → per-row status valid / duplicate / error
@bank_statement_bp.route("/validate", methods=["POST"])
@login_required
def api_bank_statement_validate():
    return validate_statement(request.get_json() or {}, _uid())


# import valid rows: { bankAccountId, fileName, rows[] }
@bank_statement_bp.route("/import", methods=["POST"])
@login_required
def api_bank_statement_import():
    return import_statement(request.get_json() or {}, _uid())


# import history ?bankAccountId
@bank_statement_bp.route("/batches", methods=["GET"])
@login_required
def api_bank_statement_batches():
    return list_batches(request.args.to_dict(), _uid())


# undo an import (only while nothing is linked)
@bank_statement_bp.route("/batches/<int:batch_id>/revert", methods=["POST"])
@login_required
def api_bank_statement_revert(batch_id):
    return revert_batch(batch_id, _uid())


# ?bankAccountId&batchId&site&type&status&fromDate&toDate&search&page&pageSize
@bank_statement_bp.route("/transactions", methods=["GET"])
@login_required
def api_bank_statement_transactions():
    return list_transactions(request.args.to_dict(), _uid())


@bank_statement_bp.route("/transactions/<int:txn_id>/history", methods=["GET"])
@login_required
def api_bank_statement_txn_history(txn_id):
    return transaction_history(txn_id, _uid())


# petty cash docket picker ?projectCode&bankCashId&kind=bank|upi|all&docketId&fromDate&toDate&search
@bank_statement_bp.route("/available-for-docket", methods=["GET"])
@login_required
def api_bank_statement_available_for_docket():
    return available_for_docket(request.args.to_dict(), _uid())
