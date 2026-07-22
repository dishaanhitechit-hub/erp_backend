from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

# MAINTENANCE: tracks which user is in the middle of a write operation
from app.utils.txn_tracker import TransactionTracker

from app.modules.resources.srn.service import (
    get_pw_orders_by_vendor,
    get_pw_order_items_for_srn,
    create_srn,
    get_srn_list,
    get_srn_details,
    submit_srn,
    approve_srn,
    reback_srn,
    reject_srn,
    edit_srn,
    get_srn_history,
    get_srn_by_uuid,
)

srn_bp = Blueprint("srn", __name__)


# ==========================================
# GET PW ORDERS BY VENDOR  (filter panel)
# ==========================================

@srn_bp.route("/vendor-orders", methods=["GET"])
@jwt_required()
def api_vendor_orders():

    data = {
        "vendorId":        request.args.get("vendorId"),
        "projectCode":     request.args.get("projectCode"),
        "categoryCode":    request.args.get("categoryCode"),
        "subCategoryCode": request.args.get("subCategoryCode"),
        "costHead":        request.args.get("costHead"),
    }

    return get_pw_orders_by_vendor(data)


# ==========================================
# GET PW ORDER ITEMS FOR SRN GRID
# ==========================================

@srn_bp.route("/order-items/<int:order_id>", methods=["GET"])
@jwt_required()
def api_order_items_for_srn(order_id):

    return get_pw_order_items_for_srn(order_id)


# ==========================================
# CREATE SRN
# ==========================================

@srn_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_srn():

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user has started creating a SRN
    TransactionTracker.mark_open(user_id, "srn_create")

    response = create_srn(data=dict(request.form), user_id=user_id, files=request.files)

    # MAINTENANCE: SRN saved — mark closed
    TransactionTracker.mark_closed(user_id)

    return response


# ==========================================
# LIST
# ==========================================

@srn_bp.route("/list", methods=["GET"])
@jwt_required()
def api_srn_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_srn_list(data)


# ==========================================
# DETAILS
# ==========================================

@srn_bp.route("/details/<int:srn_id>", methods=["GET"])
@jwt_required()
def api_srn_details(srn_id):

    return get_srn_details(srn_id)


# ==========================================
# SUBMIT
# ==========================================

@srn_bp.route("/submit/<int:srn_id>", methods=["POST"])
@jwt_required()
def api_submit_srn(srn_id):

    user_id = get_jwt_identity()

    return submit_srn(srn_id=srn_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@srn_bp.route("/approve/<int:srn_id>", methods=["POST"])
@jwt_required()
def api_approve_srn(srn_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return approve_srn(
        srn_id=srn_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@srn_bp.route("/reback/<int:srn_id>", methods=["POST"])
@jwt_required()
def api_reback_srn(srn_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reback_srn(
        srn_id=srn_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@srn_bp.route("/reject/<int:srn_id>", methods=["POST"])
@jwt_required()
def api_reject_srn(srn_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reject_srn(
        srn_id=srn_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# EDIT SRN
# ==========================================

@srn_bp.route("/edit/<int:srn_id>", methods=["PUT"])
@jwt_required()
def api_edit_srn(srn_id):

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user is editing an existing SRN
    TransactionTracker.mark_open(user_id, "srn_edit")

    response = edit_srn(
        srn_id=srn_id,
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

@srn_bp.route("/history/<int:srn_id>", methods=["GET"])
@jwt_required()
def api_srn_history(srn_id):

    return get_srn_history(srn_id)


# ==========================================
# GET FULL SRN DETAILS BY UUID
# GET /api/srn/uuid/<srn_uuid>
# ==========================================

@srn_bp.route("/uuid/<string:srn_uuid>", methods=["GET"])
def api_srn_by_uuid(srn_uuid):
    return get_srn_by_uuid(srn_uuid)
