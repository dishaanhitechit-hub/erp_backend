from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.machinery_mgmt.pm_id_service import (
    create_pm_id,
    get_pm_id_list,
    get_pm_id_detail,
    get_pm_id_by_uid,
    edit_pm_id,
)

pm_id_bp = Blueprint("pm_id", __name__)


@pm_id_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_pm_id():
    user_id = get_jwt_identity()
    return create_pm_id(request, user_id)


@pm_id_bp.route("/list", methods=["GET"])
@jwt_required()
def api_pm_id_list():
    return get_pm_id_list()


@pm_id_bp.route("/<int:pm_id>", methods=["GET"])
@jwt_required()
def api_pm_id_detail(pm_id):
    return get_pm_id_detail(pm_id)


@pm_id_bp.route("/by-uid/<string:pm_uid>", methods=["GET"])
@jwt_required()
def api_pm_id_by_uid(pm_uid):
    return get_pm_id_by_uid(pm_uid)


@pm_id_bp.route("/edit/<int:pm_id>", methods=["PUT"])
@jwt_required()
def api_edit_pm_id(pm_id):
    user_id = get_jwt_identity()
    return edit_pm_id(pm_id, request, user_id)
