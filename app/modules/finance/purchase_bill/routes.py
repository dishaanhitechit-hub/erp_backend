from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.purchase_bill.service import (
    get_vendor_orders,
    get_brr_list_for_order,
    get_brr_items_grouped,
    create_purchase_bill,
    get_purchase_bill_list,
    get_purchase_bill_details,
    edit_purchase_bill,
    submit_purchase_bill,
    approve_purchase_bill,
    reback_purchase_bill,
    reject_purchase_bill,
    get_purchase_bill_history,
    get_purchase_bill_my_approval_status,
)

purchase_bill_bp = Blueprint("purchase_bill", __name__)


# ── 1. VENDOR ORDERS ──────────────────────────────────────────────
@purchase_bill_bp.route("/vendor-orders", methods=["GET"])
@login_required
def api_vendor_orders():
    return get_vendor_orders(request.args.to_dict())


# ── 2. BRR LIST FOR ORDER ─────────────────────────────────────────
@purchase_bill_bp.route("/brr-list", methods=["GET"])
@login_required
def api_brr_list():
    return get_brr_list_for_order(request.args.to_dict())


# ── 3. BRR ITEMS GROUPED BY CC CODE ──────────────────────────────
@purchase_bill_bp.route("/brr-items", methods=["GET"])
@login_required
def api_brr_items():
    return get_brr_items_grouped(request.args.to_dict())


# ── 4. CREATE ─────────────────────────────────────────────────────
@purchase_bill_bp.route("/create", methods=["POST"])
@login_required
def api_create_purchase_bill():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_purchase_bill(data, user_id)


# ── 5. LIST ───────────────────────────────────────────────────────
@purchase_bill_bp.route("/list", methods=["GET"])
@login_required
def api_purchase_bill_list():
    return get_purchase_bill_list(request.args.to_dict())


# ── 6. DETAILS ────────────────────────────────────────────────────
@purchase_bill_bp.route("/<int:bill_id>", methods=["GET"])
@login_required
def api_purchase_bill_details(bill_id):
    return get_purchase_bill_details(bill_id)


# ── 7. EDIT ───────────────────────────────────────────────────────
@purchase_bill_bp.route("/edit/<int:bill_id>", methods=["PUT"])
@login_required
def api_edit_purchase_bill(bill_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_purchase_bill(bill_id, data, user_id)


# ── 8. SUBMIT ─────────────────────────────────────────────────────
@purchase_bill_bp.route("/submit/<int:bill_id>", methods=["POST"])
@login_required
def api_submit_purchase_bill(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_purchase_bill(bill_id, user_id)


# ── 9. APPROVE ────────────────────────────────────────────────────
@purchase_bill_bp.route("/approve/<int:bill_id>", methods=["POST"])
@login_required
def api_approve_purchase_bill(bill_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_purchase_bill(bill_id, approved_by, data.get("comments"))


# ── 10. REBACK ────────────────────────────────────────────────────
@purchase_bill_bp.route("/reback/<int:bill_id>", methods=["POST"])
@login_required
def api_reback_purchase_bill(bill_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_purchase_bill(bill_id, reback_by, data.get("comments"))


# ── 11. REJECT ────────────────────────────────────────────────────
@purchase_bill_bp.route("/reject/<int:bill_id>", methods=["POST"])
@login_required
def api_reject_purchase_bill(bill_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_purchase_bill(bill_id, rejected_by, data.get("comments"))


# ── 12. HISTORY ───────────────────────────────────────────────────
@purchase_bill_bp.route("/history/<int:bill_id>", methods=["GET"])
@login_required
def api_purchase_bill_history(bill_id):
    return get_purchase_bill_history(bill_id)


# ── 13. MY APPROVAL STATUS ────────────────────────────────────────
@purchase_bill_bp.route("/my-approval-status/<int:bill_id>", methods=["GET"])
@login_required
def api_purchase_bill_my_approval_status(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_purchase_bill_my_approval_status(bill_id, user_id)
