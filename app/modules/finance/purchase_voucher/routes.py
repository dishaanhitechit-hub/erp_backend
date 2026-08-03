from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.purchase_voucher.service import (
    create_purchase_voucher,
    get_purchase_voucher_list,
    get_purchase_voucher_details,
    get_purchase_voucher_by_uuid,
    edit_purchase_voucher,
    submit_purchase_voucher,
    approve_purchase_voucher,
    reback_purchase_voucher,
    reject_purchase_voucher,
    get_purchase_voucher_history,
    get_purchase_voucher_my_approval_status,
)

purchase_voucher_bp = Blueprint("purchase_voucher", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@purchase_voucher_bp.route("/create", methods=["POST"])
@login_required
def api_create_purchase_voucher():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_purchase_voucher(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@purchase_voucher_bp.route("/list", methods=["GET"])
@login_required
def api_purchase_voucher_list():
    return get_purchase_voucher_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@purchase_voucher_bp.route("/<int:voucher_id>", methods=["GET"])
@login_required
def api_purchase_voucher_details(voucher_id):
    return get_purchase_voucher_details(voucher_id)


# ── 4. UUID (public — no JWT) ─────────────────────────────────────
@purchase_voucher_bp.route("/uuid/<string:voucher_uuid>", methods=["GET"])
def api_purchase_voucher_by_uuid(voucher_uuid):
    return get_purchase_voucher_by_uuid(voucher_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@purchase_voucher_bp.route("/edit/<int:voucher_id>", methods=["PUT"])
@login_required
def api_edit_purchase_voucher(voucher_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_purchase_voucher(voucher_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@purchase_voucher_bp.route("/submit/<int:voucher_id>", methods=["POST"])
@login_required
def api_submit_purchase_voucher(voucher_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_purchase_voucher(voucher_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@purchase_voucher_bp.route("/approve/<int:voucher_id>", methods=["POST"])
@login_required
def api_approve_purchase_voucher(voucher_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_purchase_voucher(voucher_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@purchase_voucher_bp.route("/reback/<int:voucher_id>", methods=["POST"])
@login_required
def api_reback_purchase_voucher(voucher_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_purchase_voucher(voucher_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@purchase_voucher_bp.route("/reject/<int:voucher_id>", methods=["POST"])
@login_required
def api_reject_purchase_voucher(voucher_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_purchase_voucher(voucher_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@purchase_voucher_bp.route("/history/<int:voucher_id>", methods=["GET"])
@login_required
def api_purchase_voucher_history(voucher_id):
    return get_purchase_voucher_history(voucher_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@purchase_voucher_bp.route("/my-approval-status/<int:voucher_id>", methods=["GET"])
@login_required
def api_purchase_voucher_my_approval_status(voucher_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_purchase_voucher_my_approval_status(voucher_id, user_id)
