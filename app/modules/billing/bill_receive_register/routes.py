from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.txn_tracker import TransactionTracker

from app.modules.billing.bill_receive_register.service import (
    get_orders_by_vendor,
    create_brr,
    get_brr_list,
    get_brr_details,
    edit_brr,
    submit_brr,
    approve_brr,
    reback_brr,
    reject_brr,
    get_brr_history,
)

brr_bp = Blueprint("brr", __name__)


# ==========================================
# GET ORDERS BY VENDOR (filter panel)
# ==========================================

@brr_bp.route("/vendor-orders", methods=["GET"])
@jwt_required()
def api_brr_vendor_orders():
    data = {
        "vendorId":      request.args.get("vendorId"),
        "projectCode":   request.args.get("projectCode"),
        "orderCategory": request.args.get("orderCategory"),
    }
    return get_orders_by_vendor(data)


# ==========================================
# CREATE BRR
# ==========================================

@brr_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_brr():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brr_create")
    response = create_brr(data=dict(request.form), user_id=user_id, files=request.files)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# LIST
# ==========================================

@brr_bp.route("/list", methods=["GET"])
@jwt_required()
def api_brr_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_brr_list(data)


# ==========================================
# DETAILS
# ==========================================

@brr_bp.route("/details/<int:brr_id>", methods=["GET"])
@jwt_required()
def api_brr_details(brr_id):
    return get_brr_details(brr_id)


# ==========================================
# EDIT
# ==========================================

@brr_bp.route("/edit/<int:brr_id>", methods=["PUT"])
@jwt_required()
def api_edit_brr(brr_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brr_edit")
    response = edit_brr(brr_id=brr_id, data=dict(request.form), user_id=user_id, files=request.files)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# SUBMIT
# ==========================================

@brr_bp.route("/submit/<int:brr_id>", methods=["POST"])
@jwt_required()
def api_submit_brr(brr_id):
    user_id = get_jwt_identity()
    return submit_brr(brr_id=brr_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@brr_bp.route("/approve/<int:brr_id>", methods=["POST"])
@jwt_required()
def api_approve_brr(brr_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_brr(brr_id=brr_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@brr_bp.route("/reback/<int:brr_id>", methods=["POST"])
@jwt_required()
def api_reback_brr(brr_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_brr(brr_id=brr_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@brr_bp.route("/reject/<int:brr_id>", methods=["POST"])
@jwt_required()
def api_reject_brr(brr_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_brr(brr_id=brr_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# HISTORY
# ==========================================

@brr_bp.route("/history/<int:brr_id>", methods=["GET"])
@jwt_required()
def api_brr_history(brr_id):
    return get_brr_history(brr_id)
