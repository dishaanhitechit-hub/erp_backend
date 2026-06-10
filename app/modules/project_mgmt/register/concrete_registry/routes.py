from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from .service import (
    create_resigistry,
    get_registry_list,
    get_registry_by_id,
    update_registry,
    submit_registry,
    approve_registry,
    reback_registry,
    reject_registry,
    get_registry_history,
)

concrete_registry_bp = Blueprint("concrete_registry", __name__)


@concrete_registry_bp.route("/create", methods=["POST"])
@jwt_required()
def create_route():
    user_id = get_jwt_identity()
    return create_resigistry(request, user_id=user_id)


@concrete_registry_bp.route("/list", methods=["GET"])
@jwt_required()
def list_route():
    return get_registry_list(request)


@concrete_registry_bp.route("/list/<int:registry_id>", methods=["GET"])
@jwt_required()
def get_by_id_route(registry_id):
    return get_registry_by_id(registry_id)


@concrete_registry_bp.route("/update/<int:registry_id>", methods=["PUT"])
@jwt_required()
def update_route(registry_id):
    user_id = get_jwt_identity()
    return update_registry(registry_id, request, user_id=user_id)


# ==========================================
# SUBMIT
# ==========================================

@concrete_registry_bp.route("/submit/<int:registry_id>", methods=["POST"])
@jwt_required()
def submit_route(registry_id):
    user_id = get_jwt_identity()
    return submit_registry(registry_id=registry_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@concrete_registry_bp.route("/approve/<int:registry_id>", methods=["POST"])
@jwt_required()
def approve_route(registry_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return approve_registry(
        registry_id=registry_id,
        approved_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@concrete_registry_bp.route("/reback/<int:registry_id>", methods=["POST"])
@jwt_required()
def reback_route(registry_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reback_registry(
        registry_id=registry_id,
        reback_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# REJECT
# ==========================================

@concrete_registry_bp.route("/reject/<int:registry_id>", methods=["POST"])
@jwt_required()
def reject_route(registry_id):
    user_id = get_jwt_identity()
    data = request.json or {}
    return reject_registry(
        registry_id=registry_id,
        rejected_by=user_id,
        comments=data.get("comments")
    )


# ==========================================
# HISTORY
# ==========================================

@concrete_registry_bp.route("/history/<int:registry_id>", methods=["GET"])
@jwt_required()
def history_route(registry_id):
    return get_registry_history(registry_id)
