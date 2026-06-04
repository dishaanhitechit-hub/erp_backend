from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.grn.service import (
    get_orders_by_vendor,
    get_order_items_for_grn,
    create_grn,
    get_grn_list,
    get_grn_details,
    submit_grn,
    approve_grn,
    reback_grn,
    reject_grn,
    edit_grn,
    get_grn_history,
)

grn_bp = Blueprint("grn", __name__)


# ==========================================
# GET ORDERS BY VENDOR  (filter panel)
# ==========================================

@grn_bp.route(
    "/vendor-orders",
    methods=["GET"]
)
@jwt_required()
def api_vendor_orders():

    data = {
        "vendorId":         request.args.get("vendorId"),
        "projectCode":      request.args.get("projectCode"),
        "receivedCategory": request.args.get("receivedCategory"),
        "itemCategory":     request.args.get("itemCategory"),
        "costHead":         request.args.get("costHead"),
    }

    return get_orders_by_vendor(data)


# ==========================================
# GET ORDER ITEMS FOR GRN GRID
# ==========================================

@grn_bp.route(
    "/order-items/<int:order_id>",
    methods=["GET"]
)
@jwt_required()
def api_order_items_for_grn(order_id):

    # grn_id = request.args.get("grnId", type=int)

    return get_order_items_for_grn(order_id)   ##, grn_id=grn_id)


# ==========================================
# CREATE GRN
# ==========================================

@grn_bp.route(
    "/create",
    methods=["POST"]
)
@jwt_required()
def api_create_grn():

    user_id = get_jwt_identity()

    data = dict(request.form)

    return create_grn(
        data=data,
        user_id=user_id,
        files=request.files
    )


# ==========================================
# LIST
# ==========================================

@grn_bp.route(
    "/list",
    methods=["GET"]
)
@jwt_required()
def api_grn_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_grn_list(data)


# ==========================================
# DETAILS
# ==========================================

@grn_bp.route(
    "/details/<int:grn_id>",
    methods=["GET"]
)
@jwt_required()
def api_grn_details(grn_id):

    return get_grn_details(grn_id)


# ==========================================
# SUBMIT
# ==========================================

@grn_bp.route(
    "/submit/<int:grn_id>",
    methods=["POST"]
)
@jwt_required()
def api_submit_grn(grn_id):

    user_id = get_jwt_identity()

    return submit_grn(
        grn_id=grn_id,
        submitted_by=user_id
    )


# ==========================================
# APPROVE
# ==========================================

@grn_bp.route(
    "/approve/<int:grn_id>",
    methods=["POST"]
)
@jwt_required()
def api_approve_grn(grn_id):

    user_id = get_jwt_identity()

    data = request.json or {}

    return approve_grn(
        grn_id=grn_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@grn_bp.route(
    "/reback/<int:grn_id>",
    methods=["POST"]
)
@jwt_required()
def api_reback_grn(grn_id):

    user_id = get_jwt_identity()

    data = request.json or {}

    return reback_grn(
        grn_id=grn_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@grn_bp.route(
    "/reject/<int:grn_id>",
    methods=["POST"]
)
@jwt_required()
def api_reject_grn(grn_id):

    user_id = get_jwt_identity()

    data = request.json or {}

    return reject_grn(
        grn_id=grn_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# EDIT GRN
# ==========================================

@grn_bp.route(
    "/edit/<int:grn_id>",
    methods=["PUT"]
)
@jwt_required()
def api_edit_grn(grn_id):

    user_id = get_jwt_identity()

    data = dict(request.form)

    return edit_grn(
        grn_id=grn_id,
        data=data,
        user_id=user_id,
        files=request.files
    )


# ==========================================
# HISTORY
# ==========================================

@grn_bp.route(
    "/history/<int:grn_id>",
    methods=["GET"]
)
@jwt_required()
def api_grn_history(grn_id):

    return get_grn_history(grn_id)
