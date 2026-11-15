from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from . import service as svc

mis_sprint_bp = Blueprint("mis_sprint", __name__)


def _body():
    return request.get_json(silent=True) or {}


@mis_sprint_bp.route("", methods=["GET"])
@jwt_required()
def api_list():
    # ?projectCode=<code>|company &status=Planned,Active &sprintType=Weekly|Monthly
    return svc.list_sprints(request.args, get_jwt_identity())


@mis_sprint_bp.route("", methods=["POST"])
@jwt_required()
def api_create():
    # { name?, sprintType, startDate?, endDate?, goal?, projectCode?, start?: bool }
    return svc.create_sprint(_body(), get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>", methods=["GET"])
@jwt_required()
def api_get(sprint_id):
    return svc.get_sprint(sprint_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>", methods=["PUT"])
@jwt_required()
def api_update(sprint_id):
    return svc.update_sprint(sprint_id, _body(), get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>", methods=["DELETE"])
@jwt_required()
def api_delete(sprint_id):
    return svc.delete_sprint(sprint_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/start", methods=["POST"])
@jwt_required()
def api_start(sprint_id):
    return svc.start_sprint(sprint_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/close", methods=["POST"])
@jwt_required()
def api_close(sprint_id):
    # { moveTo: "backlog" | <sprintId> }
    return svc.close_sprint(sprint_id, _body(), get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/report", methods=["GET"])
@jwt_required()
def api_report(sprint_id):
    return svc.sprint_report(sprint_id, get_jwt_identity())
