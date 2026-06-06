from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from .service import (
    create_drawing_register,
    get_drawing_register_list,
    get_drawing_register_details,
    edit_drawing_register,
    submit_drawing_register,
    approve_drawing_register,
    reback_drawing_register,
    reject_drawing_register,
    get_drawing_register_history,
)

drawing_register_bp = Blueprint("drawing_register", __name__)


# ==========================================
# CREATE
# ==========================================

@drawing_register_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_drawing_register():

    user_id = get_jwt_identity()
    data = dict(request.form)

    return create_drawing_register(
        data=data,
        user_id=user_id,
        files=request.files
    )


# ==========================================
# LIST
# ==========================================

@drawing_register_bp.route("/list", methods=["GET"])
@jwt_required()
def api_drawing_register_list():

    data = {
        "projectCode":    request.args.get("projectCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }

    return get_drawing_register_list(data)


# ==========================================
# DETAILS
# ==========================================

@drawing_register_bp.route("/details/<int:dr_id>", methods=["GET"])
@jwt_required()
def api_drawing_register_details(dr_id):

    return get_drawing_register_details(dr_id)


# ==========================================
# EDIT
# ==========================================

@drawing_register_bp.route("/edit/<int:dr_id>", methods=["PUT"])
@jwt_required()
def api_edit_drawing_register(dr_id):

    user_id = get_jwt_identity()
    data = dict(request.form)

    return edit_drawing_register(
        dr_id=dr_id,
        data=data,
        user_id=user_id,
        files=request.files
    )


# ==========================================
# SUBMIT
# ==========================================

@drawing_register_bp.route("/submit/<int:dr_id>", methods=["POST"])
@jwt_required()
def api_submit_drawing_register(dr_id):

    user_id = get_jwt_identity()

    return submit_drawing_register(dr_id=dr_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@drawing_register_bp.route("/approve/<int:dr_id>", methods=["POST"])
@jwt_required()
def api_approve_drawing_register(dr_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return approve_drawing_register(
        dr_id=dr_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@drawing_register_bp.route("/reback/<int:dr_id>", methods=["POST"])
@jwt_required()
def api_reback_drawing_register(dr_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return reback_drawing_register(
        dr_id=dr_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@drawing_register_bp.route("/reject/<int:dr_id>", methods=["POST"])
@jwt_required()
def api_reject_drawing_register(dr_id):

    user_id = get_jwt_identity()
    data = request.json or {}

    return reject_drawing_register(
        dr_id=dr_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# HISTORY
# ==========================================

@drawing_register_bp.route("/history/<int:dr_id>", methods=["GET"])
@jwt_required()
def api_drawing_register_history(dr_id):

    return get_drawing_register_history(dr_id)
