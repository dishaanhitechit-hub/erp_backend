from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.petty_cash.budget.service import (
    create_petty_cash_budget,
    get_petty_cash_budget_list,
    get_petty_cash_budget_details,
    get_petty_cash_budget_by_uuid,
    edit_petty_cash_budget,
    submit_petty_cash_budget,
    approve_petty_cash_budget,
    reback_petty_cash_budget,
    reject_petty_cash_budget,
    get_petty_cash_budget_history,
    get_petty_cash_budget_my_approval_status,
    revise_petty_cash_budget,
    get_petty_cash_budget_revision_history,
)

petty_cash_budget_bp = Blueprint("petty_cash_budget", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/create", methods=["POST"])
@login_required
def api_create_petty_cash_budget():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_petty_cash_budget(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/list", methods=["GET"])
@login_required
def api_petty_cash_budget_list():
    return get_petty_cash_budget_list(request.args.to_dict())


# ── 3. GET BY ID ──────────────────────────────────────────────────
@petty_cash_budget_bp.route("/<int:budget_id>", methods=["GET"])
@login_required
def api_petty_cash_budget_details(budget_id):
    return get_petty_cash_budget_details(budget_id)


# ── 4. GET BY UUID (no-auth) ──────────────────────────────────────
@petty_cash_budget_bp.route("/uuid/<string:budget_uuid>", methods=["GET"])
def api_petty_cash_budget_by_uuid(budget_uuid):
    return get_petty_cash_budget_by_uuid(budget_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/edit/<int:budget_id>", methods=["PUT"])
@login_required
def api_edit_petty_cash_budget(budget_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_petty_cash_budget(budget_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/submit/<int:budget_id>", methods=["POST"])
@login_required
def api_submit_petty_cash_budget(budget_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_petty_cash_budget(budget_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/approve/<int:budget_id>", methods=["POST"])
@login_required
def api_approve_petty_cash_budget(budget_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_petty_cash_budget(budget_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/reback/<int:budget_id>", methods=["POST"])
@login_required
def api_reback_petty_cash_budget(budget_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_petty_cash_budget(budget_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@petty_cash_budget_bp.route("/reject/<int:budget_id>", methods=["POST"])
@login_required
def api_reject_petty_cash_budget(budget_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_petty_cash_budget(budget_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@petty_cash_budget_bp.route("/history/<int:budget_id>", methods=["GET"])
@login_required
def api_petty_cash_budget_history(budget_id):
    return get_petty_cash_budget_history(budget_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@petty_cash_budget_bp.route("/my-approval-status/<int:budget_id>", methods=["GET"])
@login_required
def api_petty_cash_budget_my_approval_status(budget_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_petty_cash_budget_my_approval_status(budget_id, user_id)


# ── 12. REVISE (post-approval, approver only) ─────────────────────
@petty_cash_budget_bp.route("/revise/<int:budget_id>", methods=["PUT"])
@login_required
def api_revise_petty_cash_budget(budget_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return revise_petty_cash_budget(budget_id, data, user_id)


# ── 13. REVISION HISTORY ─────────────────────────────────────────
@petty_cash_budget_bp.route("/revision-history/<int:budget_id>", methods=["GET"])
@login_required
def api_petty_cash_budget_revision_history(budget_id):
    return get_petty_cash_budget_revision_history(budget_id)
