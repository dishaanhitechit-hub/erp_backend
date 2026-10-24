from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from .service import (
    get_payroll_list, get_payslip, run_payroll,
    update_payroll_status, get_department_summary,
)

payroll_bp = Blueprint("payroll", __name__)


@payroll_bp.route("", methods=["GET"])
@jwt_required()
def api_payroll_list():
    data = {
        "month": request.args.get("month"),
        "year": request.args.get("year"),
        "status": request.args.get("status", ""),
        "search": request.args.get("search", ""),
    }
    return get_payroll_list(data)


@payroll_bp.route("/payslip/<int:entry_id>", methods=["GET"])
@jwt_required()
def api_payslip(entry_id):
    return get_payslip(entry_id)


@payroll_bp.route("/run", methods=["POST"])
@jwt_required()
def api_run_payroll():
    body = request.get_json() or {}
    body["created_by"] = get_jwt_identity()
    return run_payroll(body)


@payroll_bp.route("/<int:entry_id>/status", methods=["PUT"])
@jwt_required()
def api_update_status(entry_id):
    return update_payroll_status(entry_id, request.get_json() or {})


@payroll_bp.route("/department-summary", methods=["GET"])
@jwt_required()
def api_dept_summary():
    data = {
        "month": request.args.get("month"),
        "year": request.args.get("year"),
    }
    return get_department_summary(data)
