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


# ── Boards planning (capacity, burndown) ──────────────────────────────────
from app.modules.mis.workitem import planning as _planning  # noqa: E402


@mis_sprint_bp.route("/<int:sprint_id>/capacity", methods=["GET"])
@jwt_required()
def api_capacity(sprint_id):
    return _planning.get_capacity(sprint_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/capacity", methods=["PUT"])
@jwt_required()
def api_set_capacity(sprint_id):
    # { members: [{ userId, hoursPerDay, daysOff: ["YYYY-MM-DD"] }] }
    return _planning.set_capacity(sprint_id, _body(), get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/burndown", methods=["GET"])
@jwt_required()
def api_burndown(sprint_id):
    return _planning.burndown(sprint_id, get_jwt_identity())


# ── Boards Scrum: stand-up + retrospective ─────────────────────────────────
from app.modules.mis.workitem import scrum as _scrum  # noqa: E402


@mis_sprint_bp.route("/<int:sprint_id>/standup", methods=["GET"])
@jwt_required()
def api_standup(sprint_id):
    return _scrum.standup(sprint_id, request.args, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/retro", methods=["GET"])
@jwt_required()
def api_retro_list(sprint_id):
    return _scrum.retro_list(sprint_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/retro", methods=["POST"])
@jwt_required()
def api_retro_add(sprint_id):
    return _scrum.retro_add(sprint_id, _body(), get_jwt_identity())       # { category, text }


@mis_sprint_bp.route("/<int:sprint_id>/retro/<int:item_id>", methods=["DELETE"])
@jwt_required()
def api_retro_delete(sprint_id, item_id):
    return _scrum.retro_delete(sprint_id, item_id, get_jwt_identity())


@mis_sprint_bp.route("/<int:sprint_id>/retro/<int:item_id>/to-backlog", methods=["POST"])
@jwt_required()
def api_retro_to_backlog(sprint_id, item_id):
    return _scrum.retro_to_backlog(sprint_id, item_id, _body(), get_jwt_identity())
