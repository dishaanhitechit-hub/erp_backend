from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from .service import (
    create_hindrance_register,
    get_hindrance_register_list,
    get_hindrance_register_details,
    get_hindrance_register_by_uuid,
    edit_hindrance_register,
    submit_hindrance_register,
    approve_hindrance_register,
    reback_hindrance_register,
    reject_hindrance_register,
    delete_hindrance_register,
    get_hindrance_register_history,
    get_hindrance_register_my_approval_status,
)

hindrance_register_bp = Blueprint("hindrance_register", __name__)


# ==========================================
# CREATE
# ==========================================

@hindrance_register_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_hindrance_register():
    user_id = get_jwt_identity()
    data = dict(request.form)
    return create_hindrance_register(data=data, user_id=user_id, files=request.files)


# ==========================================
# LIST
# ==========================================

@hindrance_register_bp.route("/list", methods=["GET"])
@jwt_required()
def api_hindrance_register_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_hindrance_register_list(data)


# ==========================================
# DETAILS BY ID
# ==========================================

@hindrance_register_bp.route("/details/<int:hr_id>", methods=["GET"])
@jwt_required()
def api_hindrance_register_details(hr_id):
    return get_hindrance_register_details(hr_id)


# ==========================================
# DETAILS BY UUID (public – no JWT)
# ==========================================

@hindrance_register_bp.route("/uuid/<string:hr_uuid>", methods=["GET"])
def api_hindrance_register_by_uuid(hr_uuid):
    return get_hindrance_register_by_uuid(hr_uuid)


# ==========================================
# EDIT
# ==========================================

@hindrance_register_bp.route("/edit/<int:hr_id>", methods=["PUT"])
@jwt_required()
def api_edit_hindrance_register(hr_id):
    user_id = get_jwt_identity()
    data = dict(request.form)
    return edit_hindrance_register(hr_id=hr_id, data=data, user_id=user_id, files=request.files)


# ==========================================
# SUBMIT
# ==========================================

@hindrance_register_bp.route("/submit/<int:hr_id>", methods=["POST"])
@jwt_required()
def api_submit_hindrance_register(hr_id):
    user_id = get_jwt_identity()
    return submit_hindrance_register(hr_id=hr_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@hindrance_register_bp.route("/approve/<int:hr_id>", methods=["POST"])
@jwt_required()
def api_approve_hindrance_register(hr_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return approve_hindrance_register(hr_id=hr_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@hindrance_register_bp.route("/reback/<int:hr_id>", methods=["POST"])
@jwt_required()
def api_reback_hindrance_register(hr_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reback_hindrance_register(hr_id=hr_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@hindrance_register_bp.route("/reject/<int:hr_id>", methods=["POST"])
@jwt_required()
def api_reject_hindrance_register(hr_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reject_hindrance_register(hr_id=hr_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# DELETE
# ==========================================

@hindrance_register_bp.route("/delete/<int:hr_id>", methods=["DELETE"])
@jwt_required()
def api_delete_hindrance_register(hr_id):
    return delete_hindrance_register(hr_id)


# ==========================================
# HISTORY
# ==========================================

@hindrance_register_bp.route("/history/<int:hr_id>", methods=["GET"])
@jwt_required()
def api_hindrance_register_history(hr_id):
    return get_hindrance_register_history(hr_id)


# ==========================================
# MY APPROVAL STATUS
# ==========================================

@hindrance_register_bp.route("/my-approval-status/<int:hr_id>", methods=["GET"])
@login_required
def api_hindrance_register_my_approval_status(hr_id):
    user = g.current_user
    return get_hindrance_register_my_approval_status(hr_id, user["id"])
