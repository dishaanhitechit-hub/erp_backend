from flask import Blueprint, request
from flask import g
from app.middleware.auth_middleware import login_required
from app.modules.finance.sale_bill.service import (
    get_certified_bills_for_order,
    get_certified_bill_items_grouped,
    create_sale_bill,
    get_sale_bill_list,
    get_sale_bill_details,
    edit_sale_bill,
    submit_sale_bill,
    approve_sale_bill,
    reback_sale_bill,
    reject_sale_bill,
    get_sale_bill_history,
    get_sale_bill_my_approval_status,
    get_sale_bill_by_uuid,
)

sale_bill_bp = Blueprint("sale_bill", __name__)


# ── 1. CERTIFIED BILLS LOOKUP ─────────────────────────────────────
@sale_bill_bp.route("/certified-bills", methods=["GET"])
@login_required
def api_certified_bills():
    return get_certified_bills_for_order(request.args.to_dict())


# ── 2. ITEMS GROUPED BY CC CODE ───────────────────────────────────
@sale_bill_bp.route("/certified-bill-items", methods=["GET"])
@login_required
def api_certified_bill_items():
    return get_certified_bill_items_grouped(request.args.to_dict())


# ── 3. CREATE ─────────────────────────────────────────────────────
@sale_bill_bp.route("/create", methods=["POST"])
@login_required
def api_create_sale_bill():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_sale_bill(data, user_id)


# ── 4. LIST ───────────────────────────────────────────────────────
@sale_bill_bp.route("/list", methods=["GET"])
@login_required
def api_sale_bill_list():
    return get_sale_bill_list(request.args.to_dict())


# ── 5. DETAILS ────────────────────────────────────────────────────
@sale_bill_bp.route("/<int:bill_id>", methods=["GET"])
@login_required
def api_sale_bill_details(bill_id):
    return get_sale_bill_details(bill_id)


# ── 6. EDIT ───────────────────────────────────────────────────────
@sale_bill_bp.route("/edit/<int:bill_id>", methods=["PUT"])
@login_required
def api_edit_sale_bill(bill_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_sale_bill(bill_id, data, user_id)


# ── 7. SUBMIT ─────────────────────────────────────────────────────
@sale_bill_bp.route("/submit/<int:bill_id>", methods=["POST"])
@login_required
def api_submit_sale_bill(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_sale_bill(bill_id, user_id)


# ── 8. APPROVE ────────────────────────────────────────────────────
@sale_bill_bp.route("/approve/<int:bill_id>", methods=["POST"])
@login_required
def api_approve_sale_bill(bill_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_sale_bill(bill_id, approved_by, data.get("comments"))


# ── 9. REBACK ─────────────────────────────────────────────────────
@sale_bill_bp.route("/reback/<int:bill_id>", methods=["POST"])
@login_required
def api_reback_sale_bill(bill_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_sale_bill(bill_id, reback_by, data.get("comments"))


# ── 10. REJECT ────────────────────────────────────────────────────
@sale_bill_bp.route("/reject/<int:bill_id>", methods=["POST"])
@login_required
def api_reject_sale_bill(bill_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_sale_bill(bill_id, rejected_by, data.get("comments"))


# ── 11. HISTORY ───────────────────────────────────────────────────
@sale_bill_bp.route("/history/<int:bill_id>", methods=["GET"])
@login_required
def api_sale_bill_history(bill_id):
    return get_sale_bill_history(bill_id)


# ── 12. MY APPROVAL STATUS ────────────────────────────────────────
@sale_bill_bp.route("/my-approval-status/<int:bill_id>", methods=["GET"])
@login_required
def api_sale_bill_my_approval_status(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_sale_bill_my_approval_status(bill_id, user_id)


# ── 13. UUID (public — no JWT) ────────────────────────────────────
@sale_bill_bp.route("/uuid/<string:sale_bill_uuid>", methods=["GET"])
def api_sale_bill_by_uuid(sale_bill_uuid):
    return get_sale_bill_by_uuid(sale_bill_uuid)
