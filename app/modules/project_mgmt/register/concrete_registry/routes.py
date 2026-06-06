from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from .service import create_resigistry, get_registry_list, get_registry_by_id, update_registry

concrete_registry_bp = Blueprint("concrete_registry", __name__)


@concrete_registry_bp.route("/create", methods=["POST"])
@jwt_required()
def create_route():
    return create_resigistry(request)


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
    return update_registry(registry_id, request)
