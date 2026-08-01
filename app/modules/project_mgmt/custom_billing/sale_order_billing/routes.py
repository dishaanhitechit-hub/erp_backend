from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required
from app.utils.txn_tracker import TransactionTracker

from app.modules.project_mgmt.custom_billing.sale_order_billing.service import (
    get_order_lookup,
    create_sale_order,
    get_sale_order_list,
    get_sale_order_details,
    edit_sale_order,
    submit_sale_order,
    approve_sale_order,
    reback_sale_order,
    reject_sale_order,
    get_sale_order_history,
    get_sale_order_my_approval_status,
    get_sale_order_by_uuid,
)

sale_order_billing_bp = Blueprint("sale_order_billing", __name__)


# ==========================================
# OG SALE ORDER LOOKUP
# ==========================================

@sale_order_billing_bp.route("/order-lookup", methods=["GET"])
@jwt_required()
def api_order_lookup():
    data = {
        "ogSaleOrderNo": request.args.get("ogSaleOrderNo"),
        "projectCode":   request.args.get("projectCode"),
    }
    return get_order_lookup(data)


# ==========================================
# CREATE
# ==========================================

@sale_order_billing_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_sale_order():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "sale_order_billing_create")
    response = create_sale_order(data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# LIST
# ==========================================

@sale_order_billing_bp.route("/list", methods=["GET"])
@jwt_required()
def api_sale_order_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "ogSaleOrderNo":  request.args.get("ogSaleOrderNo"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_sale_order_list(data)


# ==========================================
# DETAILS
# ==========================================

@sale_order_billing_bp.route("/details/<int:so_id>", methods=["GET"])
@jwt_required()
def api_sale_order_details(so_id):
    return get_sale_order_details(so_id)


# ==========================================
# EDIT
# ==========================================

@sale_order_billing_bp.route("/edit/<int:so_id>", methods=["PUT"])
@jwt_required()
def api_edit_sale_order(so_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "sale_order_billing_edit")
    response = edit_sale_order(so_id=so_id, data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# SUBMIT
# ==========================================

@sale_order_billing_bp.route("/submit/<int:so_id>", methods=["POST"])
@jwt_required()
def api_submit_sale_order(so_id):
    user_id = get_jwt_identity()
    return submit_sale_order(so_id=so_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@sale_order_billing_bp.route("/approve/<int:so_id>", methods=["POST"])
@jwt_required()
def api_approve_sale_order(so_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_sale_order(so_id=so_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@sale_order_billing_bp.route("/reback/<int:so_id>", methods=["POST"])
@jwt_required()
def api_reback_sale_order(so_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_sale_order(so_id=so_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@sale_order_billing_bp.route("/reject/<int:so_id>", methods=["POST"])
@jwt_required()
def api_reject_sale_order(so_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_sale_order(so_id=so_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# HISTORY
# ==========================================

@sale_order_billing_bp.route("/history/<int:so_id>", methods=["GET"])
@jwt_required()
def api_sale_order_history(so_id):
    return get_sale_order_history(so_id)


# ==========================================
# MY APPROVAL STATUS
# ==========================================

@sale_order_billing_bp.route("/my-approval-status/<int:so_id>", methods=["GET"])
@login_required
def api_sale_order_my_approval_status(so_id):
    user = g.current_user
    return get_sale_order_my_approval_status(so_id, user["id"])


# ==========================================
# GET BY UUID  (public — no JWT)
# ==========================================

@sale_order_billing_bp.route("/uuid/<string:so_uuid>", methods=["GET"])
def api_sale_order_by_uuid(so_uuid):
    return get_sale_order_by_uuid(so_uuid)
