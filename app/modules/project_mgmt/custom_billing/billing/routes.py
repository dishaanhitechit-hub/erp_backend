from flask import Blueprint, request
from flask import g
from app.middleware.auth_middleware import login_required
from app.modules.project_mgmt.custom_billing.billing.service import (
    get_order_lookup,
    create_billing,
    get_billing_list,
    get_billing_details,
    edit_billing,
    submit_billing,
    approve_billing,
    reback_billing,
    reject_billing,
    get_billing_history,
    get_billing_my_approval_status,
    get_billing_by_uuid,
)

billing_bp = Blueprint("billing", __name__)


# ── 1. ORDER LOOKUP ──────────────────────────────────────────────
@billing_bp.route("/order-lookup", methods=["GET"])
@login_required
def api_order_lookup():
    return get_order_lookup({
        "ogSaleOrderNo": request.args.get("ogSaleOrderNo"),
        "projectCode":   request.args.get("projectCode"),
        "mode":          request.args.get("mode"),
        "claimBillId":   request.args.get("claimBillId"),
    })


# ── 2. CREATE ────────────────────────────────────────────────────
@billing_bp.route("/create", methods=["POST"])
@login_required
def api_create_billing():
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_billing(request, user_id)


# ── 3. LIST ──────────────────────────────────────────────────────
@billing_bp.route("/list", methods=["GET"])
@login_required
def api_billing_list():
    return get_billing_list(request.args.to_dict())


# ── 4. DETAILS ───────────────────────────────────────────────────
@billing_bp.route("/<int:bill_id>", methods=["GET"])
@login_required
def api_billing_details(bill_id):
    return get_billing_details(bill_id)


# ── 5. EDIT ──────────────────────────────────────────────────────
@billing_bp.route("/edit/<int:bill_id>", methods=["PUT"])
@login_required
def api_edit_billing(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_billing(bill_id, request, user_id)


# ── 6. SUBMIT ────────────────────────────────────────────────────
@billing_bp.route("/submit/<int:bill_id>", methods=["POST"])
@login_required
def api_submit_billing(bill_id):
    submitted_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_billing(bill_id, submitted_by)


# ── 7. APPROVE ───────────────────────────────────────────────────
@billing_bp.route("/approve/<int:bill_id>", methods=["POST"])
@login_required
def api_approve_billing(bill_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_billing(bill_id, approved_by, data.get("comments"))


# ── 8. REBACK ────────────────────────────────────────────────────
@billing_bp.route("/reback/<int:bill_id>", methods=["POST"])
@login_required
def api_reback_billing(bill_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_billing(bill_id, reback_by, data.get("comments"))


# ── 9. REJECT ────────────────────────────────────────────────────
@billing_bp.route("/reject/<int:bill_id>", methods=["POST"])
@login_required
def api_reject_billing(bill_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_billing(bill_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ──────────────────────────────────────────────────
@billing_bp.route("/history/<int:bill_id>", methods=["GET"])
@login_required
def api_billing_history(bill_id):
    return get_billing_history(bill_id)


# ── 11. MY APPROVAL STATUS ───────────────────────────────────────
@billing_bp.route("/my-approval-status/<int:bill_id>", methods=["GET"])
@login_required
def api_billing_my_approval_status(bill_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_billing_my_approval_status(bill_id, user_id)


# ── 12. UUID (public — no JWT) ───────────────────────────────────
@billing_bp.route("/uuid/<string:billing_uuid>", methods=["GET"])
def api_billing_by_uuid(billing_uuid):
    return get_billing_by_uuid(billing_uuid)
