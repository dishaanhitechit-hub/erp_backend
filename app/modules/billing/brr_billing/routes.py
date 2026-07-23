from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from .service import (
    get_items_by_brr,
    create_brb,
    get_brb_list,
    get_brb_details,
    edit_brb,
    submit_brb,
    approve_brb,
    reback_brb,
    reject_brb,
    get_brb_history,
)

brb_bp = Blueprint("brb", __name__)


@brb_bp.route("/items-by-brr/<int:brr_id>", methods=["GET"])
@jwt_required()
def items_by_brr(brr_id):
    return get_items_by_brr(brr_id)


@brb_bp.route("/create", methods=["POST"])
@jwt_required()
def create():
    user_id = get_jwt_identity()
    return create_brb(request.get_json(), user_id)


@brb_bp.route("/list", methods=["GET"])
@jwt_required()
def brb_list():
    return get_brb_list(request.args)


@brb_bp.route("/details/<int:brb_id>", methods=["GET"])
@jwt_required()
def details(brb_id):
    return get_brb_details(brb_id)


@brb_bp.route("/edit/<int:brb_id>", methods=["PUT"])
@jwt_required()
def edit(brb_id):
    user_id = get_jwt_identity()
    return edit_brb(brb_id, request.get_json(), user_id)


@brb_bp.route("/submit/<int:brb_id>", methods=["POST"])
@jwt_required()
def submit(brb_id):
    user_id = get_jwt_identity()
    return submit_brb(brb_id, submitted_by=user_id)


@brb_bp.route("/approve/<int:brb_id>", methods=["POST"])
@jwt_required()
def approve(brb_id):
    user_id = get_jwt_identity()
    body    = request.get_json() or {}
    return approve_brb(brb_id, approved_by=user_id, comments=body.get("comments"))


@brb_bp.route("/reback/<int:brb_id>", methods=["POST"])
@jwt_required()
def reback(brb_id):
    user_id = get_jwt_identity()
    body    = request.get_json() or {}
    return reback_brb(brb_id, reback_by=user_id, comments=body.get("comments"))


@brb_bp.route("/reject/<int:brb_id>", methods=["POST"])
@jwt_required()
def reject(brb_id):
    user_id = get_jwt_identity()
    body    = request.get_json() or {}
    return reject_brb(brb_id, rejected_by=user_id, comments=body.get("comments"))


@brb_bp.route("/history/<int:brb_id>", methods=["GET"])
@jwt_required()
def history(brb_id):
    return get_brb_history(brb_id)
