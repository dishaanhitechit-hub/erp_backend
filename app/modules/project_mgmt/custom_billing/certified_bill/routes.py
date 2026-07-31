from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required
from app.utils.txn_tracker import TransactionTracker

from app.modules.project_mgmt.custom_billing.certified_bill.service import (
    get_order_lookup,
    create_certified_bill,
    get_certified_bill_list,
    get_certified_bill_details,
    edit_certified_bill,
    submit_certified_bill,
    approve_certified_bill,
    reback_certified_bill,
    reject_certified_bill,
    get_certified_bill_history,
    get_certified_bill_my_approval_status,
    get_certified_bill_by_uuid,
)

certified_bill_bp = Blueprint("certified_bill", __name__)


# ==========================================
# ORDER LOOKUP
# ==========================================

@certified_bill_bp.route("/order-lookup", methods=["GET"])
@jwt_required()
def api_order_lookup():
    data = {
        "orderNo":     request.args.get("orderNo"),
        "projectCode": request.args.get("projectCode"),
        "orderType":   request.args.get("orderType", "normal"),
    }
    return get_order_lookup(data)


# ==========================================
# CREATE
# ==========================================

@certified_bill_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_certified_bill():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "certified_bill_create")
    response = create_certified_bill(data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# LIST
# ==========================================

@certified_bill_bp.route("/list", methods=["GET"])
@jwt_required()
def api_certified_bill_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "orderNo":        request.args.get("orderNo"),
        "orderType":      request.args.get("orderType"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_certified_bill_list(data)


# ==========================================
# DETAILS
# ==========================================

@certified_bill_bp.route("/details/<int:cb_id>", methods=["GET"])
@jwt_required()
def api_certified_bill_details(cb_id):
    return get_certified_bill_details(cb_id)


# ==========================================
# EDIT
# ==========================================

@certified_bill_bp.route("/edit/<int:cb_id>", methods=["PUT"])
@jwt_required()
def api_edit_certified_bill(cb_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "certified_bill_edit")
    response = edit_certified_bill(cb_id=cb_id, data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# SUBMIT
# ==========================================

@certified_bill_bp.route("/submit/<int:cb_id>", methods=["POST"])
@jwt_required()
def api_submit_certified_bill(cb_id):
    user_id = get_jwt_identity()
    return submit_certified_bill(cb_id=cb_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@certified_bill_bp.route("/approve/<int:cb_id>", methods=["POST"])
@jwt_required()
def api_approve_certified_bill(cb_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_certified_bill(cb_id=cb_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@certified_bill_bp.route("/reback/<int:cb_id>", methods=["POST"])
@jwt_required()
def api_reback_certified_bill(cb_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_certified_bill(cb_id=cb_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@certified_bill_bp.route("/reject/<int:cb_id>", methods=["POST"])
@jwt_required()
def api_reject_certified_bill(cb_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_certified_bill(cb_id=cb_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# HISTORY
# ==========================================

@certified_bill_bp.route("/history/<int:cb_id>", methods=["GET"])
@jwt_required()
def api_certified_bill_history(cb_id):
    return get_certified_bill_history(cb_id)


# ==========================================
# MY APPROVAL STATUS
# ==========================================

@certified_bill_bp.route("/my-approval-status/<int:cb_id>", methods=["GET"])
@login_required
def api_certified_bill_my_approval_status(cb_id):
    user = g.current_user
    return get_certified_bill_my_approval_status(cb_id, user["id"])


# ==========================================
# GET BY UUID  (public — no JWT)
# ==========================================

@certified_bill_bp.route("/uuid/<string:cb_uuid>", methods=["GET"])
def api_certified_bill_by_uuid(cb_uuid):
    return get_certified_bill_by_uuid(cb_uuid)
