from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.project_mgmt.contract.budget.service import (
    get_sale_orders_for_dropdown,
    get_sale_order_items,
    get_cc_codes_list,
    create_budget,
    get_budget_list,
    get_budget_details,
    get_budget_by_uuid,
    edit_budget,
    submit_budget,
    approve_budget,
    reback_budget,
    reject_budget,
    get_budget_history,
    get_budget_my_approval_status,
)

budget_bp = Blueprint("budget", __name__)


# ── Lookups ─────────────────────────────────────────────────────
@budget_bp.route("/sale-orders", methods=["GET"])
@jwt_required()
def sale_orders_dropdown():
    return get_sale_orders_for_dropdown(request.args)


@budget_bp.route("/sale-order-items/<int:so_id>", methods=["GET"])
@jwt_required()
def sale_order_items(so_id):
    return get_sale_order_items(so_id)


@budget_bp.route("/cc-codes", methods=["GET"])
@jwt_required()
def cc_codes():
    return get_cc_codes_list(request.args)


# ── List & Create ────────────────────────────────────────────────
@budget_bp.route("/list", methods=["GET"])
@jwt_required()
def list_budgets():
    return get_budget_list(request.args)


@budget_bp.route("/create", methods=["POST"])
@jwt_required()
def create():
    user_id = get_jwt_identity()
    return create_budget(request.get_json(), user_id)


# ── Single record ────────────────────────────────────────────────
@budget_bp.route("/<int:budget_id>", methods=["GET"])
@jwt_required()
def details(budget_id):
    return get_budget_details(budget_id)


@budget_bp.route("/uuid/<budget_uuid>", methods=["GET"])
def get_by_uuid(budget_uuid):
    return get_budget_by_uuid(budget_uuid)


@budget_bp.route("/edit/<int:budget_id>", methods=["PUT"])
@jwt_required()
def edit(budget_id):
    user_id = get_jwt_identity()
    return edit_budget(budget_id, request.get_json(), user_id)


# ── Workflow ─────────────────────────────────────────────────────
@budget_bp.route("/submit/<int:budget_id>", methods=["POST"])
@jwt_required()
def submit(budget_id):
    user_id = get_jwt_identity()
    return submit_budget(budget_id, user_id)


@budget_bp.route("/approve/<int:budget_id>", methods=["POST"])
@jwt_required()
def approve(budget_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return approve_budget(budget_id, user_id, comments)


@budget_bp.route("/reback/<int:budget_id>", methods=["POST"])
@jwt_required()
def reback(budget_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reback_budget(budget_id, user_id, comments)


@budget_bp.route("/reject/<int:budget_id>", methods=["POST"])
@jwt_required()
def reject(budget_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reject_budget(budget_id, user_id, comments)


# ── History & approval status ────────────────────────────────────
@budget_bp.route("/history/<int:budget_id>", methods=["GET"])
@jwt_required()
def history(budget_id):
    return get_budget_history(budget_id)


@budget_bp.route("/my-approval-status/<int:budget_id>", methods=["GET"])
@jwt_required()
def my_approval_status(budget_id):
    user_id = get_jwt_identity()
    return get_budget_my_approval_status(budget_id, user_id)
