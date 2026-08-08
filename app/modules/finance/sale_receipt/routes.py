from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.sale_receipt.service import (
    get_og_sale_orders,
    create_sale_receipt,
    get_sale_receipt_list,
    get_sale_receipt_details,
    edit_sale_receipt,
    delete_sale_receipt,
)

sale_receipt_bp = Blueprint("sale_receipt", __name__)


# ── 1. APPROVED OG SALE ORDERS ────────────────────────────────────
@sale_receipt_bp.route("/og-sale-orders", methods=["GET"])
@login_required
def api_sr_og_sale_orders():
    return get_og_sale_orders(request.args.to_dict())


# ── 2. CREATE ─────────────────────────────────────────────────────
@sale_receipt_bp.route("/create", methods=["POST"])
@login_required
def api_create_sale_receipt():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_sale_receipt(data, user_id)


# ── 3. LIST ───────────────────────────────────────────────────────
@sale_receipt_bp.route("/list", methods=["GET"])
@login_required
def api_sale_receipt_list():
    return get_sale_receipt_list(request.args.to_dict())


# ── 4. DETAILS ────────────────────────────────────────────────────
@sale_receipt_bp.route("/<int:receipt_id>", methods=["GET"])
@login_required
def api_sale_receipt_details(receipt_id):
    return get_sale_receipt_details(receipt_id)


# ── 5. EDIT ───────────────────────────────────────────────────────
@sale_receipt_bp.route("/edit/<int:receipt_id>", methods=["PUT"])
@login_required
def api_edit_sale_receipt(receipt_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_sale_receipt(receipt_id, data, user_id)


# ── 6. DELETE ─────────────────────────────────────────────────────
@sale_receipt_bp.route("/delete/<int:receipt_id>", methods=["DELETE"])
@login_required
def api_delete_sale_receipt(receipt_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return delete_sale_receipt(receipt_id, user_id)
