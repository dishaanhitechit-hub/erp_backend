from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.machinery_mgmt.service_history_service import (
    create_service_history,
    get_service_history_list,
    get_service_history_detail,
    edit_service_history,
)

service_history_bp = Blueprint("pm_service_history", __name__)


@service_history_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_service_history():
    user_id = get_jwt_identity()
    return create_service_history(request, user_id)


@service_history_bp.route("/list", methods=["GET"])
@jwt_required()
def api_service_history_list():
    pm_id = request.args.get("pmId")
    return get_service_history_list(pm_id=pm_id)


@service_history_bp.route("/<int:history_id>", methods=["GET"])
@jwt_required()
def api_service_history_detail(history_id):
    return get_service_history_detail(history_id)


@service_history_bp.route("/edit/<int:history_id>", methods=["PUT"])
@jwt_required()
def api_edit_service_history(history_id):
    user_id = get_jwt_identity()
    return edit_service_history(history_id, request, user_id)
