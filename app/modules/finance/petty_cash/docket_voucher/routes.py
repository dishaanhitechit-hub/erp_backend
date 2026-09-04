from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.petty_cash.docket_voucher.service import (
    create_petty_cash_docket_voucher,
    get_petty_cash_docket_voucher_list,
    get_petty_cash_docket_voucher_details,
    get_petty_cash_docket_voucher_by_uuid,
    edit_petty_cash_docket_voucher,
    submit_petty_cash_docket_voucher,
    approve_petty_cash_docket_voucher,
    reback_petty_cash_docket_voucher,
    reject_petty_cash_docket_voucher,
    get_petty_cash_docket_voucher_history,
    get_petty_cash_docket_voucher_my_approval_status,
    get_budget_rows_for_voucher,
)

petty_cash_docket_voucher_bp = Blueprint("petty_cash_docket_voucher", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/create", methods=["POST"])
@login_required
def api_create_petty_cash_docket_voucher():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_petty_cash_docket_voucher(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/list", methods=["GET"])
@login_required
def api_petty_cash_docket_voucher_list():
    return get_petty_cash_docket_voucher_list(request.args.to_dict())


# ── 3. GET BY ID ──────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/<int:voucher_id>", methods=["GET"])
@login_required
def api_petty_cash_docket_voucher_details(voucher_id):
    return get_petty_cash_docket_voucher_details(voucher_id)


# ── 4. GET BY UUID (no-auth) ──────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/uuid/<string:voucher_uuid>", methods=["GET"])
def api_petty_cash_docket_voucher_by_uuid(voucher_uuid):
    return get_petty_cash_docket_voucher_by_uuid(voucher_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/edit/<int:voucher_id>", methods=["PUT"])
@login_required
def api_edit_petty_cash_docket_voucher(voucher_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_petty_cash_docket_voucher(voucher_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/submit/<int:voucher_id>", methods=["POST"])
@login_required
def api_submit_petty_cash_docket_voucher(voucher_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_petty_cash_docket_voucher(voucher_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/approve/<int:voucher_id>", methods=["POST"])
@login_required
def api_approve_petty_cash_docket_voucher(voucher_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_petty_cash_docket_voucher(voucher_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/reback/<int:voucher_id>", methods=["POST"])
@login_required
def api_reback_petty_cash_docket_voucher(voucher_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_petty_cash_docket_voucher(voucher_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/reject/<int:voucher_id>", methods=["POST"])
@login_required
def api_reject_petty_cash_docket_voucher(voucher_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_petty_cash_docket_voucher(voucher_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/history/<int:voucher_id>", methods=["GET"])
@login_required
def api_petty_cash_docket_voucher_history(voucher_id):
    return get_petty_cash_docket_voucher_history(voucher_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@petty_cash_docket_voucher_bp.route("/my-approval-status/<int:voucher_id>", methods=["GET"])
@login_required
def api_petty_cash_docket_voucher_my_approval_status(voucher_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_petty_cash_docket_voucher_my_approval_status(voucher_id, user_id)


# ── 12. FETCH BUDGET ROWS (pre-fill helper) ───────────────────────
@petty_cash_docket_voucher_bp.route("/budget-rows/<int:budget_id>", methods=["GET"])
@login_required
def api_get_budget_rows_for_voucher(budget_id):
    return get_budget_rows_for_voucher(budget_id)
