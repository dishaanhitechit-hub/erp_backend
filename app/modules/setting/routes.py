# app/modules/setting/routes.py
import os
from flask import Blueprint, request ,jsonify
from app.middleware.auth_middleware import login_required
from app.response import res
from flask import send_from_directory
from app.middleware.role_middleware import require_super_admin
from .service import ( create_user,create_project,
                       # assign_role,
                       delete_role,create_approval_path,
                       get_roles_by_project_code,
                       get_all_users,get_all_project,
                    delete_project_designation,add_designation_to_project,get_user_by_id,update_user,get_project_by_id,update_project,update_roles_by_project_code)

setting_bp = Blueprint("setting", __name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads/signatures")

@setting_bp.route("/create-user", methods=["POST"])
@login_required
@require_super_admin
def create_user_route():
    result = create_user(request)

    if "error" in result:
        return res(result["error"], code=400)

    return result

@setting_bp.route("/create-project", methods=["POST"])
@login_required
@require_super_admin
def create_project_route():
    data = request.get_json()

    if not data:
        return res("No data provided", code=400)

    result = create_project(data)

    if "error" in result:
        return res(result["error"], code=400)

    return res("Project created successfully", result)

# PROJECT ROLE =

# @setting_bp.route("/assign-role", methods=["POST"])
# @login_required
# @require_super_admin
# def assign_role_route():
#     data = request.get_json()
#
#     if not data:
#         return res("No data provided", code=400)
#
#     return assign_role(data)


# @setting_bp.route("/update-role/<int:role_id>", methods=["PUT"])
# @login_required
# def update_role_route(RoleId):
#     data = request.get_json()
#
#     result = update_role(
#         role_id=RoleId,
#         user_id=data.get("user_id"),
#         designation_id=data.get("DesignationId")
#     )
#
#     if "error" in result:
#         return res(result["error"], code=400)
#
#     return res("Role updated successfully", result)


@setting_bp.route("/delete-role/<int:role_id>", methods=["DELETE"])
@login_required
@require_super_admin
def delete_role_route(role_id):
    result = delete_role(role_id)

    if "error" in result:
        return res(result["error"], code=400)

    return res("Role deleted successfully", result)


@setting_bp.route("/project-role/<string:projectCode>", methods=["GET", "PUT"])
@login_required
@require_super_admin
def handle_project_roles(projectCode):

    if request.method == "GET":
        return get_roles_by_project_code(projectCode)

    if request.method == "PUT":
        data = request.get_json()

        if not data:
            return res("No data provided", [], 400)

        return update_roles_by_project_code(projectCode, data)

# DESIGNATION

@setting_bp.route("/designation", methods=["POST"])
@login_required
@require_super_admin
def add_designation_route():
    return add_designation_to_project(request)


@setting_bp.route("/delete-project-designation", methods=["DELETE"])
@login_required
@require_super_admin
def delete_project_designation_route():
    data = request.get_json()

    if not data:
        return res("No data provided", code=400)

    result = delete_project_designation(
        ProjectId=data.get("ProjectId"),
        TeamId=data.get("TeamId"),
        DesignationId=data.get("DesignationId")
    )

    if "error" in result:
        return res(result["error"], code=400)

    return res("Designation removed from project", result)


# @setting_bp.route("/designations", methods=["GET"])
# @login_required
# def get_designations_route():
#     return res("Designations fetched", get_all_designations())


#  USERS

@setting_bp.route("/users", methods=["GET"])
@login_required
def users():

    project_code = request.args.get(
        "projectCode"
    )

    data = get_all_users(
        project_code
    )

    return res(
        "Users fetched",
        data,
        200
    )


@setting_bp.route("/uploads/signatures/<filename>")
def get_signature(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@setting_bp.route("/project-list", methods=["GET"])
@login_required
# @require_super_admin
def get_project_list_route():
    return  get_all_project()

@setting_bp.route("/user/<int:userId>", methods=["GET", "PUT"])
@login_required
@require_super_admin
def handle_user(userId):

    if request.method == "GET":
        return get_user_by_id(userId)

    if request.method == "PUT":
        # data = handle_user(request)
        return update_user(userId, request)

@setting_bp.route("/project/<int:projectId>", methods=["GET", "PUT"])
@login_required
@require_super_admin
def handle_project(projectId):

    if request.method == "GET":
        return get_project_by_id(projectId)

    if request.method == "PUT":
        data = request.get_json()
        return update_project(projectId, data)


@setting_bp.route("/approval-path", methods=["POST"] )
@login_required
@require_super_admin
def create_approval():

    data = request.get_json()

    return create_approval_path(data)



