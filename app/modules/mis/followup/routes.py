from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from . import service as svc

mis_followup_bp = Blueprint("mis_followup", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _me():
    return get_jwt_identity()


# ── lists / lookups ───────────────────────────────────────────────────
@mis_followup_bp.route("", methods=["GET"])
@jwt_required()
def api_list():
    # ?scope=board|mine|supervised|involved &projectCode=<code>|company &sprintId= | &backlog=1
    # &boardStatus=a,b &priority= &assigneeUserId= &overdue=1 &search= &page= &perPage=
    return svc.list_followups(request.args, _me())


@mis_followup_bp.route("/stats", methods=["GET"])
@jwt_required()
def api_stats():
    return svc.stats(request.args, _me())


@mis_followup_bp.route("/access", methods=["GET"])
@jwt_required()
def api_access():
    return svc.my_access(_me())


@mis_followup_bp.route("/assignable-users", methods=["GET"])
@jwt_required()
def api_assignable():
    return svc.assignable_users(request.args, _me())


@mis_followup_bp.route("/uuid/<string:fu_uuid>", methods=["GET"])
@jwt_required()
def api_by_uuid(fu_uuid):
    return svc.get_by_uuid(fu_uuid, _me())


# ── one agenda ────────────────────────────────────────────────────────
@mis_followup_bp.route("", methods=["POST"])
@jwt_required()
def api_create():
    # { title, description?, projectCode?, sprintId?, priority?, dueDate?, storyPoints?,
    #   supervisorUserId?, assigneeUserId?, instruction?, stepDueDate? }
    return svc.create_followup(_body(), _me())


@mis_followup_bp.route("/<int:fid>", methods=["GET"])
@jwt_required()
def api_get(fid):
    return svc.get_followup(fid, _me())


@mis_followup_bp.route("/<int:fid>", methods=["PUT"])
@jwt_required()
def api_update(fid):
    return svc.update_followup(fid, _body(), _me())


@mis_followup_bp.route("/<int:fid>", methods=["DELETE"])
@jwt_required()
def api_delete(fid):
    return svc.delete_followup(fid, _me())


@mis_followup_bp.route("/<int:fid>/board-status", methods=["PATCH"])
@jwt_required()
def api_board_status(fid):
    return svc.set_board_status(fid, _body(), _me())          # { boardStatus, note? }


@mis_followup_bp.route("/<int:fid>/move-sprint", methods=["PATCH"])
@jwt_required()
def api_move_sprint(fid):
    return svc.move_sprint(fid, _body(), _me())               # { sprintId | null }


@mis_followup_bp.route("/<int:fid>/comments", methods=["POST"])
@jwt_required()
def api_comment(fid):
    return svc.add_comment(fid, _body(), _me())


# ── relay ─────────────────────────────────────────────────────────────
@mis_followup_bp.route("/<int:fid>/assign", methods=["POST"])
@jwt_required()
def api_assign(fid):
    return svc.assign(fid, _body(), _me())                    # { assigneeUserId, instruction?, dueDate? }


@mis_followup_bp.route("/<int:fid>/start", methods=["POST"])
@jwt_required()
def api_start(fid):
    return svc.start(fid, _me())


@mis_followup_bp.route("/<int:fid>/handoff", methods=["POST"])
@jwt_required()
def api_handoff(fid):
    return svc.handoff(fid, _body(), _me())                   # { note?, nextAssigneeUserId, instruction?, dueDate? }


@mis_followup_bp.route("/<int:fid>/return", methods=["POST"])
@jwt_required()
def api_return(fid):
    return svc.return_to_supervisor(fid, _body(), _me())      # { note? }


@mis_followup_bp.route("/<int:fid>/close", methods=["POST"])
@jwt_required()
def api_close(fid):
    return svc.close(fid, _body(), _me())                     # { note? }


@mis_followup_bp.route("/<int:fid>/reject", methods=["POST"])
@jwt_required()
def api_reject(fid):
    return svc.reject(fid, _body(), _me())                    # { note, assigneeUserId?, instruction?, dueDate? }
