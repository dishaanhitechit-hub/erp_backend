from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required

from .service import (
    get_sale_orders_for_lookup,
    get_sale_order_items_for_ua,
    get_claim_bills_for_so,
    get_claim_bill_items_for_ua,
    create_ua,
    get_ua_list,
    get_ua_details,
    edit_ua,
    submit_ua,
    approve_ua,
    reback_ua,
    reject_ua,
    get_ua_history,
    get_ua_my_approval_status,
    get_ua_by_uuid,
)

ua_bp = Blueprint("uncertain_allocation", __name__)

MODULE = "uncertain_allocation"


# ── 1. SALE ORDER LOOKUP ─────────────────────────────────────────
@ua_bp.route("/sale-order-lookup", methods=["GET"])
@login_required
def api_sale_order_lookup():
    return get_sale_orders_for_lookup({
        "projectCode": request.args.get("projectCode"),
        "search":      request.args.get("search"),
    })


# ── 1b. SALE ORDER ITEMS ─────────────────────────────────────────
@ua_bp.route("/sale-order-items/<int:og_sale_order_id>", methods=["GET"])
@login_required
def api_sale_order_items(og_sale_order_id):
    project_code = request.args.get("projectCode")
    return get_sale_order_items_for_ua(og_sale_order_id, project_code)


# ── 1c. CLAIM BILL LOOKUP ────────────────────────────────────────
@ua_bp.route("/claim-bills/<int:og_sale_order_id>", methods=["GET"])
@login_required
def api_claim_bills(og_sale_order_id):
    return get_claim_bills_for_so(og_sale_order_id)


# ── 1d. CLAIM BILL ITEMS ─────────────────────────────────────────
@ua_bp.route("/claim-bill-items/<int:billing_id>", methods=["GET"])
@login_required
def api_claim_bill_items(billing_id):
    return get_claim_bill_items_for_ua(billing_id)


# ── 2. CREATE ────────────────────────────────────────────────────
@ua_bp.route("/create", methods=["POST"])
@login_required
def api_create():
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_ua(request.get_json(), user_id)


# ── 3. LIST ──────────────────────────────────────────────────────
@ua_bp.route("/list", methods=["GET"])
@login_required
def api_list():
    return get_ua_list(request.args.to_dict())


# ── 4. DETAILS ───────────────────────────────────────────────────
@ua_bp.route("/<int:ua_id>", methods=["GET"])
@login_required
def api_details(ua_id):
    return get_ua_details(ua_id)


# ── 5. EDIT ──────────────────────────────────────────────────────
@ua_bp.route("/edit/<int:ua_id>", methods=["PUT"])
@login_required
def api_edit(ua_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_ua(ua_id, request.get_json(), user_id)


# ── 6. SUBMIT ────────────────────────────────────────────────────
@ua_bp.route("/submit/<int:ua_id>", methods=["POST"])
@login_required
def api_submit(ua_id):
    submitted_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_ua(ua_id, submitted_by)


# ── 7. APPROVE ───────────────────────────────────────────────────
@ua_bp.route("/approve/<int:ua_id>", methods=["POST"])
@login_required
def api_approve(ua_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_ua(ua_id, approved_by, data.get("comments"))


# ── 8. REBACK ────────────────────────────────────────────────────
@ua_bp.route("/reback/<int:ua_id>", methods=["POST"])
@login_required
def api_reback(ua_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_ua(ua_id, reback_by, data.get("comments"))


# ── 9. REJECT ────────────────────────────────────────────────────
@ua_bp.route("/reject/<int:ua_id>", methods=["POST"])
@login_required
def api_reject(ua_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_ua(ua_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ──────────────────────────────────────────────────
@ua_bp.route("/history/<int:ua_id>", methods=["GET"])
@login_required
def api_history(ua_id):
    return get_ua_history(ua_id)


# ── 11. MY APPROVAL STATUS ───────────────────────────────────────
@ua_bp.route("/my-approval-status/<int:ua_id>", methods=["GET"])
@login_required
def api_my_approval_status(ua_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_ua_my_approval_status(ua_id, user_id)


# ── 12. GET BY UUID (no auth — for print/share) ───────────────────
@ua_bp.route("/uuid/<string:ua_uuid>", methods=["GET"])
def api_get_by_uuid(ua_uuid):
    return get_ua_by_uuid(ua_uuid)


@ua_bp.route("/<int:ua_id>", methods=["DELETE"])
@login_required
def api_delete_uncertain_allocation(ua_id):
    from .service import delete_uncertain_allocation
    return delete_uncertain_allocation(ua_id)
