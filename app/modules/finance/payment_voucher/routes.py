from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.payment_voucher.service import (
    get_approved_purchase_vouchers,
    get_purchase_voucher_payment_items,
    create_payment_voucher,
    get_payment_voucher_list,
    get_payment_voucher_details,
    get_payment_voucher_by_uuid,
    edit_payment_voucher,
    submit_payment_voucher,
    approve_payment_voucher,
    reback_payment_voucher,
    reject_payment_voucher,
    get_payment_voucher_history,
    get_payment_voucher_my_approval_status,
)

payment_voucher_bp = Blueprint("payment_voucher", __name__)


# ── LOOKUP: Approved purchase vouchers for JV dropdown ────────────
@payment_voucher_bp.route("/approved-purchase-vouchers", methods=["GET"])
@login_required
def api_approved_purchase_vouchers():
    return get_approved_purchase_vouchers(request.args.to_dict())


# ── LOOKUP: Items + GST of a purchase voucher with paid/balance ───
@payment_voucher_bp.route("/purchase-voucher-items/<int:pv_id>", methods=["GET"])
@login_required
def api_purchase_voucher_payment_items(pv_id):
    return get_purchase_voucher_payment_items(pv_id)


# ── 1. CREATE ─────────────────────────────────────────────────────
@payment_voucher_bp.route("/create", methods=["POST"])
@login_required
def api_create_payment_voucher():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_payment_voucher(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@payment_voucher_bp.route("/list", methods=["GET"])
@login_required
def api_payment_voucher_list():
    return get_payment_voucher_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@payment_voucher_bp.route("/<int:pvm_id>", methods=["GET"])
@login_required
def api_payment_voucher_details(pvm_id):
    return get_payment_voucher_details(pvm_id)


# ── 4. UUID (public — no JWT) ─────────────────────────────────────
@payment_voucher_bp.route("/uuid/<string:voucher_uuid>", methods=["GET"])
def api_payment_voucher_by_uuid(voucher_uuid):
    return get_payment_voucher_by_uuid(voucher_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@payment_voucher_bp.route("/edit/<int:pvm_id>", methods=["PUT"])
@login_required
def api_edit_payment_voucher(pvm_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_payment_voucher(pvm_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@payment_voucher_bp.route("/submit/<int:pvm_id>", methods=["POST"])
@login_required
def api_submit_payment_voucher(pvm_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_payment_voucher(pvm_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@payment_voucher_bp.route("/approve/<int:pvm_id>", methods=["POST"])
@login_required
def api_approve_payment_voucher(pvm_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_payment_voucher(pvm_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@payment_voucher_bp.route("/reback/<int:pvm_id>", methods=["POST"])
@login_required
def api_reback_payment_voucher(pvm_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_payment_voucher(pvm_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@payment_voucher_bp.route("/reject/<int:pvm_id>", methods=["POST"])
@login_required
def api_reject_payment_voucher(pvm_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_payment_voucher(pvm_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@payment_voucher_bp.route("/history/<int:pvm_id>", methods=["GET"])
@login_required
def api_payment_voucher_history(pvm_id):
    return get_payment_voucher_history(pvm_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@payment_voucher_bp.route("/my-approval-status/<int:pvm_id>", methods=["GET"])
@login_required
def api_payment_voucher_my_approval_status(pvm_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_payment_voucher_my_approval_status(pvm_id, user_id)
