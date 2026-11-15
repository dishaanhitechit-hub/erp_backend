from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from . import service as svc

mis_task_bp = Blueprint("mis_task", __name__)


def _body():
    return request.get_json(silent=True) or {}


@mis_task_bp.route("", methods=["GET"])
@jwt_required()
def api_list():
    # ?scope=mine|assigned_by_me|team|all &status=a,b &priority= &ownerUserId= &projectCode=<code>|company
    # &fromDate= &toDate= &overdue=1 &search= &page= &perPage=
    return svc.list_tasks(request.args, get_jwt_identity())


@mis_task_bp.route("", methods=["POST"])
@jwt_required()
def api_create():
    return svc.create_task(_body(), get_jwt_identity())


@mis_task_bp.route("/stats", methods=["GET"])
@jwt_required()
def api_stats():
    return svc.task_stats(request.args, get_jwt_identity())


@mis_task_bp.route("/access", methods=["GET"])
@jwt_required()
def api_access():
    return svc.my_access(get_jwt_identity())


@mis_task_bp.route("/assignable-users", methods=["GET"])
@jwt_required()
def api_assignable_users():
    return svc.assignable_users(request.args, get_jwt_identity())


@mis_task_bp.route("/owners", methods=["GET"])
@jwt_required()
def api_owners():
    return svc.viewable_owners(request.args, get_jwt_identity())


@mis_task_bp.route("/reopen-requests", methods=["GET"])
@jwt_required()
def api_reopen_requests():
    # ?scope=decide (waiting for me as higher level) | mine (I asked)
    return svc.list_reopen_requests(request.args, get_jwt_identity())


@mis_task_bp.route("/reopen-requests/<int:request_id>/decide", methods=["POST"])
@jwt_required()
def api_reopen_decide(request_id):
    return svc.decide_reopen(request_id, _body(), get_jwt_identity())     # { approve: bool, note? }


@mis_task_bp.route("/uuid/<string:task_uuid>", methods=["GET"])
@jwt_required()
def api_get_by_uuid(task_uuid):
    return svc.get_task_by_uuid(task_uuid, get_jwt_identity())


@mis_task_bp.route("/<int:task_id>", methods=["GET"])
@jwt_required()
def api_get(task_id):
    return svc.get_task(task_id, get_jwt_identity())


@mis_task_bp.route("/<int:task_id>", methods=["PUT"])
@jwt_required()
def api_update(task_id):
    return svc.update_task(task_id, _body(), get_jwt_identity())


@mis_task_bp.route("/<int:task_id>/status", methods=["PATCH"])
@jwt_required()
def api_status(task_id):
    return svc.change_status(task_id, _body(), get_jwt_identity())


@mis_task_bp.route("/<int:task_id>/comments", methods=["POST"])
@jwt_required()
def api_comment(task_id):
    return svc.add_comment(task_id, _body(), get_jwt_identity())


@mis_task_bp.route("/<int:task_id>", methods=["DELETE"])
@jwt_required()
def api_delete(task_id):
    return svc.delete_task(task_id, get_jwt_identity())


@mis_task_bp.route("/<int:task_id>/start", methods=["POST"])
@jwt_required()
def api_start(task_id):
    return svc.start_task(task_id, get_jwt_identity())


@mis_task_bp.route("/<int:task_id>/reopen-request", methods=["POST"])
@jwt_required()
def api_reopen_request(task_id):
    return svc.request_reopen(task_id, _body(), get_jwt_identity())       # { reason }


@mis_task_bp.route("/<int:task_id>/reopen", methods=["POST"])
@jwt_required()
def api_reopen(task_id):
    return svc.reopen_direct(task_id, _body(), get_jwt_identity())        # { note? } higher level only
