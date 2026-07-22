from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

# MAINTENANCE: tracks which user is in the middle of a write operation
from app.utils.txn_tracker import TransactionTracker

from app.modules.resources.gin.service import (
    get_orders_by_vendor,
    get_order_items_for_gin,
    create_gin,
    get_gin_list,
    get_gin_details,
    submit_gin,
    approve_gin,
    reback_gin,
    reject_gin,
    edit_gin,
    get_gin_history,
    get_gin_by_uuid,
)

gin_bp = Blueprint("gin", __name__)


# ==========================================
# GET ORDERS BY VENDOR  (filter panel)
# ==========================================

@gin_bp.route("/vendor-orders", methods=["GET"])
@jwt_required()
def api_vendor_orders():

    data = {
        "vendorId":      request.args.get("vendorId"),
        "projectCode":   request.args.get("projectCode"),
        "issueCategory": request.args.get("issueCategory"),
        "itemCategory":  request.args.get("itemCategory"),
        "costHead":      request.args.get("costHead"),
    }

    return get_orders_by_vendor(data)


# ==========================================
# GET ORDER ITEMS FOR GIN GRID
# ==========================================

@gin_bp.route("/order-items/<int:order_id>", methods=["GET"])
@jwt_required()
def api_order_items_for_gin(order_id):

    return get_order_items_for_gin(order_id)


# ==========================================
# CREATE GIN
# ==========================================

@gin_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_gin():

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user has started creating a GIN
    TransactionTracker.mark_open(user_id, "gin_create")

    response = create_gin(data=dict(request.form), user_id=user_id, files=request.files)

    # MAINTENANCE: GIN saved — mark closed
    TransactionTracker.mark_closed(user_id)

    return response


# ==========================================
# LIST
# ==========================================

@gin_bp.route("/list", methods=["GET"])
@jwt_required()
def api_gin_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_gin_list(data)


# ==========================================
# DETAILS
# ==========================================

@gin_bp.route("/details/<int:gin_id>", methods=["GET"])
@jwt_required()
def api_gin_details(gin_id):

    return get_gin_details(gin_id)


# ==========================================
# SUBMIT
# ==========================================

@gin_bp.route("/submit/<int:gin_id>", methods=["POST"])
@jwt_required()
def api_submit_gin(gin_id):

    user_id = get_jwt_identity()

    return submit_gin(gin_id=gin_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@gin_bp.route("/approve/<int:gin_id>", methods=["POST"])
@jwt_required()
def api_approve_gin(gin_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return approve_gin(
        gin_id=gin_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@gin_bp.route("/reback/<int:gin_id>", methods=["POST"])
@jwt_required()
def api_reback_gin(gin_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return reback_gin(
        gin_id=gin_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@gin_bp.route("/reject/<int:gin_id>", methods=["POST"])
@jwt_required()
def api_reject_gin(gin_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return reject_gin(
        gin_id=gin_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# EDIT GIN
# ==========================================

@gin_bp.route("/edit/<int:gin_id>", methods=["PUT"])
@jwt_required()
def api_edit_gin(gin_id):

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user is editing an existing GIN
    TransactionTracker.mark_open(user_id, "gin_edit")

    response = edit_gin(
        gin_id=gin_id,
        data=dict(request.form),
        user_id=user_id,
        files=request.files
    )

    # MAINTENANCE: edit complete — mark closed
    TransactionTracker.mark_closed(user_id)

    return response


# ==========================================
# HISTORY
# ==========================================

@gin_bp.route("/history/<int:gin_id>", methods=["GET"])
@jwt_required()
def api_gin_history(gin_id):

    return get_gin_history(gin_id)


# ==========================================
# GET FULL GIN DETAILS BY UUID
# GET /api/gin/uuid/<gin_uuid>
# ==========================================

@gin_bp.route("/uuid/<string:gin_uuid>", methods=["GET"])
def api_gin_by_uuid(gin_uuid):
    return get_gin_by_uuid(gin_uuid)
