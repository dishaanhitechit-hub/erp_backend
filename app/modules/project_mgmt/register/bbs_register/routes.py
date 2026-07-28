from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from .service import (
    create_bbs_register,
    get_bbs_register_list,
    get_bbs_register_details,
    get_bbs_register_by_uuid,
    edit_bbs_register,
    submit_bbs_register,
    approve_bbs_register,
    reback_bbs_register,
    reject_bbs_register,
    delete_bbs_register,
    get_bbs_register_history,
    get_bbs_register_my_approval_status,
)

bbs_register_bp = Blueprint("bbs_register", __name__)


# ==========================================
# CREATE
# ==========================================

@bbs_register_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_bbs_register():
    user_id = get_jwt_identity()
    data = dict(request.form)
    return create_bbs_register(data=data, user_id=user_id, files=request.files)


# ==========================================
# LIST
# ==========================================

@bbs_register_bp.route("/list", methods=["GET"])
@jwt_required()
def api_bbs_register_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_bbs_register_list(data)


# ==========================================
# DETAILS BY ID
# ==========================================

@bbs_register_bp.route("/details/<int:bbs_id>", methods=["GET"])
@jwt_required()
def api_bbs_register_details(bbs_id):
    return get_bbs_register_details(bbs_id)


# ==========================================
# DETAILS BY UUID (public – no JWT)
# ==========================================

@bbs_register_bp.route("/uuid/<string:bbs_uuid>", methods=["GET"])
def api_bbs_register_by_uuid(bbs_uuid):
    return get_bbs_register_by_uuid(bbs_uuid)


# ==========================================
# EDIT
# ==========================================

@bbs_register_bp.route("/edit/<int:bbs_id>", methods=["PUT"])
@jwt_required()
def api_edit_bbs_register(bbs_id):
    user_id = get_jwt_identity()
    data = dict(request.form)
    return edit_bbs_register(bbs_id=bbs_id, data=data, user_id=user_id, files=request.files)


# ==========================================
# SUBMIT
# ==========================================

@bbs_register_bp.route("/submit/<int:bbs_id>", methods=["POST"])
@jwt_required()
def api_submit_bbs_register(bbs_id):
    user_id = get_jwt_identity()
    return submit_bbs_register(bbs_id=bbs_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@bbs_register_bp.route("/approve/<int:bbs_id>", methods=["POST"])
@jwt_required()
def api_approve_bbs_register(bbs_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return approve_bbs_register(bbs_id=bbs_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@bbs_register_bp.route("/reback/<int:bbs_id>", methods=["POST"])
@jwt_required()
def api_reback_bbs_register(bbs_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reback_bbs_register(bbs_id=bbs_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@bbs_register_bp.route("/reject/<int:bbs_id>", methods=["POST"])
@jwt_required()
def api_reject_bbs_register(bbs_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reject_bbs_register(bbs_id=bbs_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# DELETE
# ==========================================

@bbs_register_bp.route("/delete/<int:bbs_id>", methods=["DELETE"])
@jwt_required()
def api_delete_bbs_register(bbs_id):
    return delete_bbs_register(bbs_id)


# ==========================================
# HISTORY
# ==========================================

@bbs_register_bp.route("/history/<int:bbs_id>", methods=["GET"])
@jwt_required()
def api_bbs_register_history(bbs_id):
    return get_bbs_register_history(bbs_id)


# ==========================================
# MY APPROVAL STATUS
# ==========================================

@bbs_register_bp.route("/my-approval-status/<int:bbs_id>", methods=["GET"])
@login_required
def api_bbs_register_my_approval_status(bbs_id):
    user = g.current_user
    return get_bbs_register_my_approval_status(bbs_id, user["id"])
