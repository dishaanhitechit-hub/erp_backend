from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.project_mgmt.custom_billing.og_sale_order.service import (
    create_og_sale_order,
    get_og_sale_order_list,
    get_og_sale_order_details,
    edit_og_sale_order,
    submit_og_sale_order,
    approve_og_sale_order,
    reback_og_sale_order,
    reject_og_sale_order,
    get_og_sale_order_history,
    get_og_sale_order_my_approval_status,
    get_og_sale_order_by_uuid,
)

og_sale_order_bp = Blueprint("og_sale_order", __name__)


# ── List & Create ───────────────────────────────────────────────
@og_sale_order_bp.route("/", methods=["GET"])
@jwt_required()
def list_og_sale_orders():
    return get_og_sale_order_list(request.args)


@og_sale_order_bp.route("/create", methods=["POST"])
@jwt_required()
def create():
    user_id = get_jwt_identity()
    return create_og_sale_order(request, user_id)


# ── Single record ───────────────────────────────────────────────
@og_sale_order_bp.route("/<int:so_id>", methods=["GET"])
@jwt_required()
def details(so_id):
    return get_og_sale_order_details(so_id)


@og_sale_order_bp.route("/<int:so_id>/edit", methods=["PUT"])
@jwt_required()
def edit(so_id):
    user_id = get_jwt_identity()
    return edit_og_sale_order(so_id, request, user_id)


# ── Workflow ────────────────────────────────────────────────────
@og_sale_order_bp.route("/<int:so_id>/submit", methods=["POST"])
@jwt_required()
def submit(so_id):
    user_id = get_jwt_identity()
    return submit_og_sale_order(so_id, user_id)


@og_sale_order_bp.route("/<int:so_id>/approve", methods=["POST"])
@jwt_required()
def approve(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return approve_og_sale_order(so_id, user_id, comments)


@og_sale_order_bp.route("/<int:so_id>/reback", methods=["POST"])
@jwt_required()
def reback(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reback_og_sale_order(so_id, user_id, comments)


@og_sale_order_bp.route("/<int:so_id>/reject", methods=["POST"])
@jwt_required()
def reject(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reject_og_sale_order(so_id, user_id, comments)


# ── History & approval status ───────────────────────────────────
@og_sale_order_bp.route("/<int:so_id>/history", methods=["GET"])
@jwt_required()
def history(so_id):
    return get_og_sale_order_history(so_id)


@og_sale_order_bp.route("/<int:so_id>/my-approval-status", methods=["GET"])
@jwt_required()
def my_approval_status(so_id):
    user_id = get_jwt_identity()
    return get_og_sale_order_my_approval_status(so_id, user_id)


# ── Public UUID endpoint (no JWT) ───────────────────────────────
@og_sale_order_bp.route("/uuid/<so_uuid>", methods=["GET"])
def get_by_uuid(so_uuid):
    return get_og_sale_order_by_uuid(so_uuid)
