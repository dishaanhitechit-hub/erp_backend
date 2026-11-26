from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from . import service as svc

mis_workitem_bp = Blueprint("mis_workitem", __name__)


def _body():
    return request.get_json(silent=True) or {}


@mis_workitem_bp.route("/meta", methods=["GET"])
@jwt_required()
def api_meta():
    return svc.meta(get_jwt_identity())


@mis_workitem_bp.route("", methods=["GET"])
@jwt_required()
def api_list():
    # ?projectCode= &type= &state= &sprintId=<id>|backlog &parentId=<id>|none &assignedTo=me|<id>
    # &tag= &blocked=1 &search= &page= &limit=
    return svc.list_items(request.args, get_jwt_identity())


@mis_workitem_bp.route("/tree", methods=["GET"])
@jwt_required()
def api_tree():
    return svc.tree(request.args, get_jwt_identity())      # ?projectCode= &sprintId= &includeDone=1


@mis_workitem_bp.route("/linked", methods=["GET"])
@jwt_required()
def api_linked():
    return svc.linked_to(request.args, get_jwt_identity())  # ?targetType=FOLLOWUP&targetId=


@mis_workitem_bp.route("", methods=["POST"])
@jwt_required()
def api_create():
    return svc.create_item(_body(), get_jwt_identity())


@mis_workitem_bp.route("/uuid/<string:item_uuid>", methods=["GET"])
@jwt_required()
def api_get_by_uuid(item_uuid):
    return svc.get_by_uuid(item_uuid, get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>", methods=["GET"])
@jwt_required()
def api_get(item_id):
    return svc.get_item(item_id, get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>", methods=["PUT"])
@jwt_required()
def api_update(item_id):
    return svc.update_item(item_id, _body(), get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>/state", methods=["PATCH"])
@jwt_required()
def api_state(item_id):
    return svc.change_state(item_id, _body(), get_jwt_identity())   # { state, comment? }


@mis_workitem_bp.route("/<int:item_id>/comments", methods=["POST"])
@jwt_required()
def api_comment(item_id):
    return svc.add_comment(item_id, _body(), get_jwt_identity())    # { comment, mentions?: [userId] }


@mis_workitem_bp.route("/<int:item_id>", methods=["DELETE"])
@jwt_required()
def api_delete(item_id):
    return svc.delete_item(item_id, get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>/links", methods=["GET"])
@jwt_required()
def api_links(item_id):
    return svc.list_links(item_id, get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>/links", methods=["POST"])
@jwt_required()
def api_add_link(item_id):
    return svc.add_link(item_id, _body(), get_jwt_identity())


@mis_workitem_bp.route("/<int:item_id>/links/<int:link_id>", methods=["DELETE"])
@jwt_required()
def api_delete_link(item_id, link_id):
    return svc.delete_link(item_id, link_id, get_jwt_identity())
