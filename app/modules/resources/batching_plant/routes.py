from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from app.modules.resources.batching_plant.service import (
    create_batching_plant,
    get_batching_plant_list,
    get_batching_plant_details,
    get_batching_plant_by_uuid,
    submit_batching_plant,
    approve_batching_plant,
    reback_batching_plant,
    reject_batching_plant,
    edit_batching_plant,
    delete_batching_plant,
    get_batching_plant_history,
    get_batching_plant_my_approval_status,
    get_approved_pw_orders,
    get_vendor_from_pw_order,
)

batching_bp = Blueprint("batching_plant", __name__)


# ==========================================
# CREATE
# ==========================================

@batching_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_batching_plant():
    user_id = get_jwt_identity()
    data = dict(request.form) if request.form else (request.json or {})
    return create_batching_plant(data, user_id)


# ==========================================
# LIST
# ==========================================

@batching_bp.route("/list", methods=["GET"])
@jwt_required()
def api_batching_plant_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_batching_plant_list(data)


# ==========================================
# DETAILS BY ID
# ==========================================

@batching_bp.route("/details/<int:bp_id>", methods=["GET"])
@jwt_required()
def api_batching_plant_details(bp_id):
    return get_batching_plant_details(bp_id)


# ==========================================
# DETAILS BY UUID (public – no JWT)
# ==========================================

@batching_bp.route("/uuid/<string:bp_uuid>", methods=["GET"])
def api_batching_plant_by_uuid(bp_uuid):
    return get_batching_plant_by_uuid(bp_uuid)


# ==========================================
# SUBMIT
# ==========================================

@batching_bp.route("/submit/<int:bp_id>", methods=["POST"])
@jwt_required()
def api_submit_batching_plant(bp_id):
    user_id = get_jwt_identity()
    return submit_batching_plant(bp_id, user_id)


# ==========================================
# APPROVE
# ==========================================

@batching_bp.route("/approve/<int:bp_id>", methods=["POST"])
@jwt_required()
def api_approve_batching_plant(bp_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return approve_batching_plant(bp_id, user_id, data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@batching_bp.route("/reback/<int:bp_id>", methods=["POST"])
@jwt_required()
def api_reback_batching_plant(bp_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reback_batching_plant(bp_id, user_id, data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@batching_bp.route("/reject/<int:bp_id>", methods=["POST"])
@jwt_required()
def api_reject_batching_plant(bp_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reject_batching_plant(bp_id, user_id, data.get("comments"))


# ==========================================
# EDIT
# ==========================================

@batching_bp.route("/edit/<int:bp_id>", methods=["PUT"])
@jwt_required()
def api_edit_batching_plant(bp_id):
    user_id = get_jwt_identity()
    data = dict(request.form) if request.form else (request.json or {})
    return edit_batching_plant(bp_id, data, user_id)


# ==========================================
# DELETE
# ==========================================

@batching_bp.route("/delete/<int:bp_id>", methods=["DELETE"])
@jwt_required()
def api_delete_batching_plant(bp_id):
    return delete_batching_plant(bp_id)


# ==========================================
# HISTORY
# ==========================================

@batching_bp.route("/history/<int:bp_id>", methods=["GET"])
@jwt_required()
def api_batching_plant_history(bp_id):
    return get_batching_plant_history(bp_id)


# ==========================================
# MY APPROVAL STATUS
# ==========================================

@batching_bp.route("/my-approval-status/<int:bp_id>", methods=["GET"])
@login_required
def api_batching_plant_my_approval_status(bp_id):
    user = g.current_user
    return get_batching_plant_my_approval_status(bp_id, user["id"])


# ==========================================
# APPROVED PW ORDERS (order dropdown helper)
# ?projectCode=X  [&vendorId=Y]
# ==========================================

@batching_bp.route("/approved-pw-orders", methods=["GET"])
@jwt_required()
def api_approved_pw_orders():
    return get_approved_pw_orders(
        project_code=request.args.get("projectCode"),
        vendor_id=request.args.get("vendorId"),
    )


# ==========================================
# VENDOR FROM PW ORDER (auto-fill helper)
# ==========================================

@batching_bp.route("/vendor-from-order/<int:pw_order_id>", methods=["GET"])
@jwt_required()
def api_vendor_from_order(pw_order_id):
    return get_vendor_from_pw_order(pw_order_id)
