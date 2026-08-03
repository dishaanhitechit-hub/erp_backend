from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.sale_receipt.service import (
    get_certified_bills_for_order,
    get_receipt_items,
    create_sale_receipt,
    get_sale_receipt_list,
    get_sale_receipt_details,
    edit_sale_receipt,
    submit_sale_receipt,
    approve_sale_receipt,
    reback_sale_receipt,
    reject_sale_receipt,
    get_sale_receipt_history,
    get_sale_receipt_my_approval_status,
    get_sale_receipt_by_uuid,
)

sale_receipt_bp = Blueprint("sale_receipt", __name__)


# ── 1. CERTIFIED BILLS LOOKUP ─────────────────────────────────────
@sale_receipt_bp.route("/certified-bills", methods=["GET"])
@login_required
def api_sr_certified_bills():
    return get_certified_bills_for_order(request.args.to_dict())


# ── 2. RECEIPT ITEMS WITH ACCOUNTING COLUMNS ─────────────────────
@sale_receipt_bp.route("/receipt-items", methods=["GET"])
@login_required
def api_sr_receipt_items():
    return get_receipt_items(request.args.to_dict())


# ── 3. CREATE ─────────────────────────────────────────────────────
@sale_receipt_bp.route("/create", methods=["POST"])
@login_required
def api_create_sale_receipt():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_sale_receipt(data, user_id)


# ── 4. LIST ───────────────────────────────────────────────────────
@sale_receipt_bp.route("/list", methods=["GET"])
@login_required
def api_sale_receipt_list():
    return get_sale_receipt_list(request.args.to_dict())


# ── 5. DETAILS ────────────────────────────────────────────────────
@sale_receipt_bp.route("/<int:receipt_id>", methods=["GET"])
@login_required
def api_sale_receipt_details(receipt_id):
    return get_sale_receipt_details(receipt_id)


# ── 6. EDIT ───────────────────────────────────────────────────────
@sale_receipt_bp.route("/edit/<int:receipt_id>", methods=["PUT"])
@login_required
def api_edit_sale_receipt(receipt_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_sale_receipt(receipt_id, data, user_id)


# ── 7. SUBMIT ─────────────────────────────────────────────────────
@sale_receipt_bp.route("/submit/<int:receipt_id>", methods=["POST"])
@login_required
def api_submit_sale_receipt(receipt_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_sale_receipt(receipt_id, user_id)


# ── 8. APPROVE ────────────────────────────────────────────────────
@sale_receipt_bp.route("/approve/<int:receipt_id>", methods=["POST"])
@login_required
def api_approve_sale_receipt(receipt_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_sale_receipt(receipt_id, approved_by, data.get("comments"))


# ── 9. REBACK ─────────────────────────────────────────────────────
@sale_receipt_bp.route("/reback/<int:receipt_id>", methods=["POST"])
@login_required
def api_reback_sale_receipt(receipt_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_sale_receipt(receipt_id, reback_by, data.get("comments"))


# ── 10. REJECT ────────────────────────────────────────────────────
@sale_receipt_bp.route("/reject/<int:receipt_id>", methods=["POST"])
@login_required
def api_reject_sale_receipt(receipt_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_sale_receipt(receipt_id, rejected_by, data.get("comments"))


# ── 11. HISTORY ───────────────────────────────────────────────────
@sale_receipt_bp.route("/history/<int:receipt_id>", methods=["GET"])
@login_required
def api_sale_receipt_history(receipt_id):
    return get_sale_receipt_history(receipt_id)


# ── 12. MY APPROVAL STATUS ────────────────────────────────────────
@sale_receipt_bp.route("/my-approval-status/<int:receipt_id>", methods=["GET"])
@login_required
def api_sale_receipt_my_approval_status(receipt_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_sale_receipt_my_approval_status(receipt_id, user_id)


# ── 13. UUID (public — no JWT) ────────────────────────────────────
@sale_receipt_bp.route("/uuid/<string:receipt_uuid>", methods=["GET"])
def api_sale_receipt_by_uuid(receipt_uuid):
    return get_sale_receipt_by_uuid(receipt_uuid)
