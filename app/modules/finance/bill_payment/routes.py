from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.bill_payment.service import (
    get_approved_purchase_bills,
    get_purchase_bill_payment_items,
    create_bill_payment_receipt,
    get_bill_payment_list,
    get_bill_payment_details,
    get_bill_payment_by_uuid,
    edit_bill_payment_receipt,
    submit_bill_payment,
    approve_bill_payment,
    reback_bill_payment,
    reject_bill_payment,
    get_bill_payment_history,
    get_bill_payment_my_approval_status,
)

bill_payment_bp = Blueprint("bill_payment", __name__)


# ── LOOKUP: Approved purchase bills for BVS dropdown ──────────────
@bill_payment_bp.route("/approved-purchase-bills", methods=["GET"])
@login_required
def api_approved_purchase_bills():
    return get_approved_purchase_bills(request.args.to_dict())


# ── LOOKUP: Items + GST of a purchase bill with paid/balance ──────
@bill_payment_bp.route("/purchase-bill-items/<int:bill_id>", methods=["GET"])
@login_required
def api_purchase_bill_payment_items(bill_id):
    return get_purchase_bill_payment_items(bill_id)


# ── 1. CREATE ─────────────────────────────────────────────────────
@bill_payment_bp.route("/create", methods=["POST"])
@login_required
def api_create_bill_payment():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_bill_payment_receipt(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@bill_payment_bp.route("/list", methods=["GET"])
@login_required
def api_bill_payment_list():
    return get_bill_payment_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@bill_payment_bp.route("/<int:receipt_id>", methods=["GET"])
@login_required
def api_bill_payment_details(receipt_id):
    return get_bill_payment_details(receipt_id)


# ── 4. UUID (public — no JWT) ─────────────────────────────────────
@bill_payment_bp.route("/uuid/<string:receipt_uuid>", methods=["GET"])
def api_bill_payment_by_uuid(receipt_uuid):
    return get_bill_payment_by_uuid(receipt_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@bill_payment_bp.route("/edit/<int:receipt_id>", methods=["PUT"])
@login_required
def api_edit_bill_payment(receipt_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_bill_payment_receipt(receipt_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@bill_payment_bp.route("/submit/<int:receipt_id>", methods=["POST"])
@login_required
def api_submit_bill_payment(receipt_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_bill_payment(receipt_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@bill_payment_bp.route("/approve/<int:receipt_id>", methods=["POST"])
@login_required
def api_approve_bill_payment(receipt_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_bill_payment(receipt_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@bill_payment_bp.route("/reback/<int:receipt_id>", methods=["POST"])
@login_required
def api_reback_bill_payment(receipt_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_bill_payment(receipt_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@bill_payment_bp.route("/reject/<int:receipt_id>", methods=["POST"])
@login_required
def api_reject_bill_payment(receipt_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_bill_payment(receipt_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@bill_payment_bp.route("/history/<int:receipt_id>", methods=["GET"])
@login_required
def api_bill_payment_history(receipt_id):
    return get_bill_payment_history(receipt_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@bill_payment_bp.route("/my-approval-status/<int:receipt_id>", methods=["GET"])
@login_required
def api_bill_payment_my_approval_status(receipt_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_bill_payment_my_approval_status(receipt_id, user_id)
