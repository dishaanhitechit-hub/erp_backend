# app/modules/setting/routes.py
import os
from flask import Blueprint, request ,jsonify
from app.middleware.auth_middleware import login_required
from app.response import res
from flask import send_from_directory
from app.middleware.role_middleware import require_super_admin
from .service import ( create_user,create_project,delete_role,
                       create_approval_path,get_approval_paths,get_roles_by_project_code,
                       get_all_users,get_all_project,get_edit_users,
                       delete_project_designation,add_designation_to_project,get_user_by_id,
                       update_user,get_project_by_id,update_project,
                       update_roles_by_project_code,delete_project_location,
                       create_project_location,update_project_location,get_project_locations,
                       )



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


@setting_bp.route(
    "/delete-project-designation",
    methods=["DELETE"]
)
@login_required
@require_super_admin
def delete_project_designation_route():

    data = request.get_json()

    if not data:

        return res(
            "No data provided",
            code=400
        )

    projectId = data.get(
        "ProjectId"
    )

    teamId = data.get(
        "TeamId"
    )

    designationId = data.get(
        "DesignationId"
    )

    if not all([
        projectId,
        teamId,
        designationId
    ]):

        return res(
            "ProjectId, TeamId and DesignationId required",
            code=400
        )

    return delete_project_designation(

        projectId=projectId,

        teamId=teamId,

        designationId=designationId

    )


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
def get_project_list_route():
    exclude_current = request.args.get("excludeCurrent", "false").lower() == "true"
    current_project_code = request.args.get("currentProjectCode")
    return get_all_project(
        exclude_current=exclude_current,
        current_project_code=current_project_code
    )

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
# @require_super_admin
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



@setting_bp.route(
    "/approval-path/list",
    methods=["GET"]
)
@login_required
@require_super_admin
def approval_path_list():

    project_code = request.args.get(
        "projectCode"
    )

    return get_approval_paths(
        project_code
    )

@setting_bp.route( "/edit-users", methods=["GET"])
@login_required
@require_super_admin
def edit_users_route():
    project_code = request.args.get(
        "projectCode"
    )
    return get_edit_users(
        project_code
    )


# ===========================
# CREATE LOCATION
# ===========================

@setting_bp.route(
    "/project-location",
    methods=["POST"]
)
@login_required
@require_super_admin
def create_project_location_route():

    return create_project_location(request)


# ===========================
# GET ALL LOCATIONS OF PROJECT
# ===========================

@setting_bp.route(
    "/project-location/<string:project_code>",
    methods=["GET"]
)
@login_required
def get_project_locations_route(

        project_code

):

    return get_project_locations(
        project_code
    )


# ===========================
# GET SINGLE LOCATION
# ===========================

# @setting_bp.route(
#     "/project-location/details/<int:location_id>",
#     methods=["GET"]
# )
# @login_required
# def get_project_location_route(
#
#         location_id
#
# ):
#
#     return get_project_location(
#         location_id
#     )


# ===========================
# UPDATE LOCATION
# ===========================

@setting_bp.route(
    "/project-location/<int:location_id>",
    methods=["PUT"]
)
@login_required
@require_super_admin
def update_project_location_route(

        location_id

):

    return update_project_location(
        request,
        location_id
    )


# ===========================
# DELETE LOCATION
# ===========================

@setting_bp.route(
    "/project-location/<int:location_id>",
    methods=["DELETE"]
)
@login_required
@require_super_admin
def delete_project_location_route(

        location_id

):

    return delete_project_location(
        location_id
    )