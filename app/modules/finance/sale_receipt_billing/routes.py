from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.sale_receipt_billing.service import (
    get_certified_bills_for_order,
    get_receipt_items,
    get_details_by_invoice_no,
    create_srb,
    get_srb_list,
    get_srb_details,
    edit_srb,
    submit_srb,
    approve_srb,
    reback_srb,
    reject_srb,
    get_srb_history,
    get_srb_my_approval_status,
    get_srb_by_uuid,
)

sale_receipt_billing_bp = Blueprint("sale_receipt_billing", __name__)


# ── 1. CERTIFIED BILLS LOOKUP ─────────────────────────────────────
@sale_receipt_billing_bp.route("/certified-bills", methods=["GET"])
@login_required
def api_srb_certified_bills():
    return get_certified_bills_for_order(request.args.to_dict())


# ── 2. RECEIPT ITEMS WITH ACCOUNTING COLUMNS ─────────────────────
@sale_receipt_billing_bp.route("/receipt-items", methods=["GET"])
@login_required
def api_srb_receipt_items():
    return get_receipt_items(request.args.to_dict())


# ── 3. INVOICE LOOKUP ────────────────────────────────────────────
@sale_receipt_billing_bp.route("/invoice-lookup", methods=["GET"])
@login_required
def api_srb_invoice_lookup():
    return get_details_by_invoice_no(request.args.to_dict())


# ── 4. CREATE ─────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/create", methods=["POST"])
@login_required
def api_create_srb():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_srb(data, user_id)


# ── 4. LIST ───────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/list", methods=["GET"])
@login_required
def api_srb_list():
    return get_srb_list(request.args.to_dict())


# ── 5. DETAILS ────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/<int:srb_id>", methods=["GET"])
@login_required
def api_srb_details(srb_id):
    return get_srb_details(srb_id)


# ── 6. EDIT ───────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/edit/<int:srb_id>", methods=["PUT"])
@login_required
def api_edit_srb(srb_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_srb(srb_id, data, user_id)


# ── 7. SUBMIT ─────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/submit/<int:srb_id>", methods=["POST"])
@login_required
def api_submit_srb(srb_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_srb(srb_id, user_id)


# ── 8. APPROVE ────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/approve/<int:srb_id>", methods=["POST"])
@login_required
def api_approve_srb(srb_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_srb(srb_id, approved_by, data.get("comments"))


# ── 9. REBACK ─────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/reback/<int:srb_id>", methods=["POST"])
@login_required
def api_reback_srb(srb_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_srb(srb_id, reback_by, data.get("comments"))


# ── 10. REJECT ────────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/reject/<int:srb_id>", methods=["POST"])
@login_required
def api_reject_srb(srb_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_srb(srb_id, rejected_by, data.get("comments"))


# ── 11. HISTORY ───────────────────────────────────────────────────
@sale_receipt_billing_bp.route("/history/<int:srb_id>", methods=["GET"])
@login_required
def api_srb_history(srb_id):
    return get_srb_history(srb_id)


# ── 12. MY APPROVAL STATUS ────────────────────────────────────────
@sale_receipt_billing_bp.route("/my-approval-status/<int:srb_id>", methods=["GET"])
@login_required
def api_srb_my_approval_status(srb_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_srb_my_approval_status(srb_id, user_id)


# ── 13. UUID (public — no JWT) ────────────────────────────────────
@sale_receipt_billing_bp.route("/uuid/<string:srb_uuid>", methods=["GET"])
def api_srb_by_uuid(srb_uuid):
    return get_srb_by_uuid(srb_uuid)
