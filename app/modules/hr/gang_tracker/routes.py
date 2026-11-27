from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.permission_middleware import page_permission
from .service import list_members, get_member, create_member, update_member, delete_member, add_followup, list_skills

gang_tracker_bp = Blueprint("gang_tracker", __name__)


@gang_tracker_bp.route("", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_list():
    return list_members(request.args.to_dict())


@gang_tracker_bp.route("/skills", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_skills():
    return list_skills()


@gang_tracker_bp.route("/<int:member_id>", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_get(member_id):
    return get_member(member_id)


@gang_tracker_bp.route("", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_create():
    user_id = get_jwt_identity()
    return create_member(request.get_json() or {}, user_id=user_id)


@gang_tracker_bp.route("/<int:member_id>", methods=["PUT"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_update(member_id):
    return update_member(member_id, request.get_json() or {})


@gang_tracker_bp.route("/<int:member_id>", methods=["DELETE"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_delete(member_id):
    return delete_member(member_id)


@gang_tracker_bp.route("/<int:member_id>/followup", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_followup(member_id):
    return add_followup(member_id, request.get_json() or {})


# ── conversations (topic → people → follow-ups) ──────────────────────────────
from . import thread_service as ts  # noqa: E402


@gang_tracker_bp.route("/people", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_people():
    return ts.list_people(request.args.to_dict())


@gang_tracker_bp.route("/threads", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_threads():
    return ts.list_threads(request.args.to_dict())


@gang_tracker_bp.route("/threads/projects", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_thread_projects():
    return ts.list_thread_projects()


@gang_tracker_bp.route("/threads/<int:thread_id>", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_thread_get(thread_id):
    return ts.get_thread(thread_id)


@gang_tracker_bp.route("/threads", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_thread_create():
    return ts.create_thread(request.get_json() or {}, user_id=int(get_jwt_identity()))


@gang_tracker_bp.route("/threads/<int:thread_id>/entries", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_thread_entry(thread_id):
    return ts.add_entry(thread_id, request.get_json() or {}, user_id=int(get_jwt_identity()))


@gang_tracker_bp.route("/threads/<int:thread_id>", methods=["PUT"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_thread_update(thread_id):
    return ts.update_thread(thread_id, request.get_json() or {})


@gang_tracker_bp.route("/threads/<int:thread_id>", methods=["DELETE"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_thread_delete(thread_id):
    return ts.delete_thread(thread_id)
