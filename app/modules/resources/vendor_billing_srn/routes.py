from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.vendor_billing_srn.service import (
    get_pw_orders_by_vendor,
    get_srns_by_order,
    create_bss,
    get_bss_list,
    get_bss_details,
    edit_bss,
    submit_bss,
    approve_bss,
    reback_bss,
    reject_bss,
    get_bss_history,
)

bss_bp = Blueprint("bss", __name__)


# ==========================================
# GET PW ORDERS BY VENDOR  (filter panel)
# ==========================================

@bss_bp.route("/vendor-orders", methods=["GET"])
@jwt_required()
def api_vendor_orders():

    data = {
        "vendorId":         request.args.get("vendorId"),
        "projectCode":      request.args.get("projectCode"),
        "receivedCategory": request.args.get("receivedCategory"),
        "itemCategory":     request.args.get("itemCategory"),
        "costHead":         request.args.get("costHead"),
    }

    return get_pw_orders_by_vendor(data)


# ==========================================
# GET SRNs BY ORDER  (selection grid)
# ==========================================

@bss_bp.route("/srns-by-order/<int:order_id>", methods=["GET"])
@jwt_required()
def api_srns_by_order(order_id):

    return get_srns_by_order(order_id)


# ==========================================
# CREATE BSS
# ==========================================

@bss_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_bss():

    user_id = get_jwt_identity()
    data    = request.get_json() or {}

    return create_bss(data=data, user_id=user_id)


# ==========================================
# LIST
# ==========================================

@bss_bp.route("/list", methods=["GET"])
@jwt_required()
def api_bss_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_bss_list(data)


# ==========================================
# DETAILS
# ==========================================

@bss_bp.route("/details/<int:bss_id>", methods=["GET"])
@jwt_required()
def api_bss_details(bss_id):

    return get_bss_details(bss_id)


# ==========================================
# EDIT
# ==========================================

@bss_bp.route("/edit/<int:bss_id>", methods=["PUT"])
@jwt_required()
def api_edit_bss(bss_id):

    user_id = get_jwt_identity()
    data    = request.get_json() or {}

    return edit_bss(bss_id=bss_id, data=data, user_id=user_id)


# ==========================================
# SUBMIT
# ==========================================

@bss_bp.route("/submit/<int:bss_id>", methods=["POST"])
@jwt_required()
def api_submit_bss(bss_id):

    user_id = get_jwt_identity()

    return submit_bss(bss_id=bss_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@bss_bp.route("/approve/<int:bss_id>", methods=["POST"])
@jwt_required()
def api_approve_bss(bss_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return approve_bss(
        bss_id=bss_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@bss_bp.route("/reback/<int:bss_id>", methods=["POST"])
@jwt_required()
def api_reback_bss(bss_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reback_bss(
        bss_id=bss_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@bss_bp.route("/reject/<int:bss_id>", methods=["POST"])
@jwt_required()
def api_reject_bss(bss_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reject_bss(
        bss_id=bss_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# HISTORY
# ==========================================

@bss_bp.route("/history/<int:bss_id>", methods=["GET"])
@jwt_required()
def api_bss_history(bss_id):

    return get_bss_history(bss_id)
