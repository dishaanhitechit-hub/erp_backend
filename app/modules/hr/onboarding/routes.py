from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.middleware.permission_middleware import page_permission
from .service import (
    get_onboarding_list, get_employee_tasks, init_onboarding,
    update_task, add_task, get_onboarding_stats,
)

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("", methods=["GET"])
@jwt_required()
@page_permission("onboarding", "VIEW")
def api_onboarding_list():
    data = {"search": request.args.get("search", "")}
    return get_onboarding_list(data)


@onboarding_bp.route("/stats", methods=["GET"])
@jwt_required()
@page_permission("onboarding", "VIEW")
def api_onboarding_stats():
    return get_onboarding_stats()


@onboarding_bp.route("/<int:emp_id>", methods=["GET"])
@jwt_required()
@page_permission("onboarding", "VIEW")
def api_employee_tasks(emp_id):
    return get_employee_tasks(emp_id)


@onboarding_bp.route("/<int:emp_id>/init", methods=["POST"])
@jwt_required()
@page_permission("onboarding", "EDIT")
def api_init_onboarding(emp_id):
    return init_onboarding(emp_id, request.get_json() or {})


@onboarding_bp.route("/<int:emp_id>/tasks", methods=["POST"])
@jwt_required()
@page_permission("onboarding", "EDIT")
def api_add_task(emp_id):
    return add_task(emp_id, request.get_json() or {})


@onboarding_bp.route("/task/<int:task_id>", methods=["PUT"])
@jwt_required()
@page_permission("onboarding", "EDIT")
def api_update_task(task_id):
    return update_task(task_id, request.get_json() or {})
