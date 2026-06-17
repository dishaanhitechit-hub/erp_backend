from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

# MAINTENANCE: tracks which user is in the middle of a write operation
from app.utils.txn_tracker import TransactionTracker

from app.modules.resources.vendor_billing_grn.service import (
    get_orders_by_vendor,
    get_grns_by_order,
    create_bvs,
    get_bvs_list,
    get_bvs_details,
    edit_bvs,
    submit_bvs,
    approve_bvs,
    reback_bvs,
    reject_bvs,
    get_bvs_history,
)

bvs_bp = Blueprint("bvs", __name__)


# ==========================================
# GET ORDERS BY VENDOR  (filter panel)
# ==========================================

@bvs_bp.route("/vendor-orders", methods=["GET"])
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
# GET GRNs BY ORDER  (selection grid)
# ==========================================

@bvs_bp.route("/grns-by-order/<int:order_id>", methods=["GET"])
@jwt_required()
def api_grns_by_order(order_id):

    return get_grns_by_order(order_id)


# ==========================================
# CREATE BVS
# ==========================================

@bvs_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_bvs():

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user has started creating a BVS (vendor billing against GRN)
    TransactionTracker.mark_open(user_id, "bvs_create")

    response = create_bvs(data=request.get_json() or {}, user_id=user_id)

    # MAINTENANCE: BVS saved — mark closed
    TransactionTracker.mark_closed(user_id)

    return response


# ==========================================
# LIST
# ==========================================

@bvs_bp.route("/list", methods=["GET"])
@jwt_required()
def api_bvs_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_bvs_list(data)


# ==========================================
# DETAILS
# ==========================================

@bvs_bp.route("/details/<int:bvs_id>", methods=["GET"])
@jwt_required()
def api_bvs_details(bvs_id):

    return get_bvs_details(bvs_id)


# ==========================================
# EDIT
# ==========================================

@bvs_bp.route("/edit/<int:bvs_id>", methods=["PUT"])
@jwt_required()
def api_edit_bvs(bvs_id):

    user_id = get_jwt_identity()

    # MAINTENANCE: mark open — user is editing an existing BVS
    TransactionTracker.mark_open(user_id, "bvs_edit")

    response = edit_bvs(bvs_id=bvs_id, data=request.get_json() or {}, user_id=user_id)

    # MAINTENANCE: edit complete — mark closed
    TransactionTracker.mark_closed(user_id)

    return response


# ==========================================
# SUBMIT
# ==========================================

@bvs_bp.route("/submit/<int:bvs_id>", methods=["POST"])
@jwt_required()
def api_submit_bvs(bvs_id):

    user_id = get_jwt_identity()

    return submit_bvs(bvs_id=bvs_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@bvs_bp.route("/approve/<int:bvs_id>", methods=["POST"])
@jwt_required()
def api_approve_bvs(bvs_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return approve_bvs(
        bvs_id=bvs_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@bvs_bp.route("/reback/<int:bvs_id>", methods=["POST"])
@jwt_required()
def api_reback_bvs(bvs_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reback_bvs(
        bvs_id=bvs_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@bvs_bp.route("/reject/<int:bvs_id>", methods=["POST"])
@jwt_required()
def api_reject_bvs(bvs_id):

    user_id = get_jwt_identity()
    data    = request.json or {}

    return reject_bvs(
        bvs_id=bvs_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# HISTORY
# ==========================================

@bvs_bp.route("/history/<int:bvs_id>", methods=["GET"])
@jwt_required()
def api_bvs_history(bvs_id):

    return get_bvs_history(bvs_id)
