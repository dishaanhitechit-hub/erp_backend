from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.middleware.permission_middleware import page_permission
from .service import get_all_employees, get_employee, create_employee, update_employee, get_departments, upload_employee_doc, get_my_profile
from flask_jwt_extended import get_jwt_identity

employee_bp = Blueprint("employee", __name__)


@employee_bp.route("/me", methods=["GET"])
@jwt_required()
def api_my_profile():
    # own profile only — safe fields, no HR permission needed (My Profile page)
    return get_my_profile(get_jwt_identity())


@employee_bp.route("", methods=["GET"])
@jwt_required()
@page_permission("employee_management", "VIEW")
def api_list_employees():
    data = {
        "search": request.args.get("search", ""),
        "department": request.args.get("department", ""),
        "status": request.args.get("status", ""),
    }
    return get_all_employees(data)


@employee_bp.route("/<int:emp_id>", methods=["GET"])
@jwt_required()
@page_permission("employee_management", "VIEW")
def api_get_employee(emp_id):
    return get_employee(emp_id)


@employee_bp.route("", methods=["POST"])
@jwt_required()
@page_permission("employee_management", "EDIT")
def api_create_employee():
    return create_employee(request.get_json() or {})


@employee_bp.route("/<int:emp_id>", methods=["PUT"])
@jwt_required()
@page_permission("employee_management", "EDIT")
def api_update_employee(emp_id):
    return update_employee(emp_id, request.get_json() or {})


@employee_bp.route("/departments", methods=["GET"])
@jwt_required()
@page_permission("employee_management", "VIEW")
def api_departments():
    return get_departments()


@employee_bp.route("/<int:emp_id>/upload-doc", methods=["POST"])
@jwt_required()
@page_permission("employee_management", "EDIT")
def api_upload_employee_doc(emp_id):
    return upload_employee_doc(emp_id, request.files.get("file"), request.form)
