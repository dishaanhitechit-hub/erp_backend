from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.machinery_mgmt.service_schedule_service import (
    create_service_schedule,
    get_service_schedule_list,
    get_service_schedule_detail,
    edit_service_schedule,
)

service_schedule_bp = Blueprint("pm_service_schedule", __name__)


@service_schedule_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_service_schedule():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    return create_service_schedule(data, user_id)


@service_schedule_bp.route("/list", methods=["GET"])
@jwt_required()
def api_service_schedule_list():
    pm_id = request.args.get("pmId")
    return get_service_schedule_list(pm_id=pm_id)


@service_schedule_bp.route("/<int:schedule_id>", methods=["GET"])
@jwt_required()
def api_service_schedule_detail(schedule_id):
    return get_service_schedule_detail(schedule_id)


@service_schedule_bp.route("/edit/<int:schedule_id>", methods=["PUT"])
@jwt_required()
def api_edit_service_schedule(schedule_id):
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    return edit_service_schedule(schedule_id, data, user_id)
