# app/modules/setting/service.py
import os
import uuid
from flask import request
from flask_jwt_extended import get_jwt_identity,get_jwt
from datetime import datetime
from app.models.user import User
from app.models.role import Role
from app.models.project import Project
from app.models.og_team import Team
from app.models.team import ProjectTeam
from app.models.project_role import ProjectUserRole
from app.models.designation import Designation
from app.models.project_designation_permission import *
from app.models.project_user_permission import *
from app.models.permission_action import *
from app.models.feature_page import *

from app.response import res
from app.cloudinary_uploader import *

from app.models.approval_path import ApprovalPath
from app.models.project_location import *
from app.modules.setting.permission_service import get_user_permissions
from collections import defaultdict

UPLOAD_FOLDER = os.path.join(os.getcwd(), "/mnt/data/uploads/signatures")



def create_user(request): # Test done & pass

    username = request.form.get("username")
    password = request.form.get("password")
    role_name = request.form.get("role")
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    wp_mobile = request.form.get("whatsapp")
    emp_code = request.form.get("employeeCode")
    is_active = request.form.get("status")


    # file
    # file = request.files.get("signature")
    signatureFile = request.files.get("signatureFile")
    # role check
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return res("Role not found", code=404)

    status_value = True

    if is_active is not None:
        status_value = str(is_active).lower() in ["true", "1", "yes"]

    # create user
    user = User(
        username=username,
        email=email,
        mobile=mobile,
        wp_mobile=wp_mobile,
        emp_code=emp_code,
        global_role=role,
        is_active= status_value
    )
    user.set_password(password)
    base_url = request.host_url
    # save signature file


    if signatureFile:
        user.signature = upload_file_to_bunny(
            file=signatureFile,
            mainFolder="users",
            subFolder=user.user_code,
            fileName="signature"
        )

    db.session.add(user)
    db.session.commit()
    data = [{
        "id": user.id,
        "username": user.username,
        "employeeCode": user.emp_code,
        "loginUserName": user.login_username,
        "email" : user.email,
        "mobile": user.mobile,
        "whatsapp": user.wp_mobile,
        "role":user.global_role.name if user.global_role else None,
        "status":user.is_active,
        "signatureUrl": user.signature

    }]
    return res(
        "User created", data,code=200
    )

def parse_date(date_str): #Test done & pass
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    except:
        return None


def create_project(data): #Test done & pass
    try:
        # Required fields
        project_code = data.get("projectCode")
        project_name = data.get("projectName")

        if not project_code or not project_name:
            return res("Project Code and Project Name required", code=400)

        #   check
        existing = Project.query.filter_by(project_code=project_code).first()
        if existing:
            return res("Project already exists", code=400)


        status = data.get("status")
        if status and status not in ["ongoing", "hold", "completed"]:
            return res("Invalid status", code=400)

        # 🔹 Create project
        project = Project(
            project_code=project_code,
            project_name=project_name,
            client_name=data.get("clientName"),
            project_details=data.get("projectDetails"),
            registered_address=data.get("registeredAddress"),
            proj_mgmt_contact_number=data.get("projMgmtContactNumber"),
            proj_mgmt_email_id=data.get("projMgmtEmailId"),
            commercial_manager=data.get("commercialManager"),
            comm_mgmt_email_id=data.get("commMgmtEmailId"),
            comm_mgmt_contact_number=data.get("commMgmtContactNumber"),
            gstn=data.get("gstn"),
            billing_address=data.get("billingAddress"),
            shipping_address=data.get("shippingAddress"),
            shipping_address_2=data.get("shippingAddress2"),
            shipping_address_3=data.get("shippingAddress3"),
            project_manager=data.get("projectManager"),
            initial_order_value=data.get("initialOrderValue"),
            revised_order_value=data.get("revisedOrderValue"),
            state=data.get("state"),
            state_code=data.get("stateCode"),
            status=status,
            #  Date fields
            schedule_date=parse_date(data.get("scheduleDate")),
            schedule_completion_date=parse_date(data.get("scheduleCompletionDate")),
            original_start_date=parse_date(data.get("originalStartDate")),
            extended_complete_date=parse_date(data.get("extendedCompleteDate")),
        )

        #  Save
        db.session.add(project)
        db.session.commit()
        data = [{
            "projectId": project.id,
            "projectCode": project.project_code
        }]
        return res(
            "Project created",data,
            code=201
        )

    except Exception as e:
        db.session.rollback()
        print("ERROR:", str(e))
        return res("Internal server error", code=500)

#Assign Role
# def assign_role(data):
#     project_id = data.get("projectId")
#     role_user_map = data.get("roleUserMap", [])
#
#     if not project_id:
#         return res("Project ID is required", code=400)
#
#     if not role_user_map:
#         return res("roleUserMap is required", code=400)
#
#     for item in role_user_map:
#         designation_id = item.get("designationId")
#         team_type = item.get("teamType")
#         user_id = item.get("userId")
#
#         pt = ProjectTeam.query.filter_by(
#             project_id=project_id,
#             designation_id=designation_id,
#             team_type=team_type
#         ).first()
#
#         if pt:
#             pt.user_id = user_id
#
#     db.session.commit()
#
#     return res("Roles assigned successfully", code=200)

# Update Role
# def update_role(roleId, userId=None, designationId=None):
#     role = ProjectUserRole.query.get(roleId)
#
#     if not role:
#         return res("Role not found", code=404)
#
#     # NULL assignment
#     if userId is not None:
#         role.user_id = userId
#
#     if designationId:
#         role.designation_id = designationId
#
#     db.session.commit()
#
#     return res("Role updated")


#Delete Role
def delete_role(roleId):
    role = ProjectUserRole.query.get(roleId)

    if not role:
        return res("Role not found", code=404)

    # also update ProjectTeam (set unassigned)
    pt = ProjectTeam.query.filter_by(
        project_id=role.project_id,
        designation_id=role.designation_id,
        team_id=role.team_id
    ).first()

    if pt:
        pt.user_id = None

    # remove role row
    db.session.delete(role)
    db.session.commit()

    return res("Role deleted successfully")


# Delete Designation
def delete_project_designation(
        projectId,
        teamId,
        designationId
):

    try:

        pt = ProjectTeam.query.filter_by(

            project_id=projectId,
            designation_id=designationId,
            team_id=teamId

        ).first()

        if not pt:

            return res(
                "Designation not found in this project",
                code=404
            )


        ProjectDesignationPermission.query.filter_by(

            project_id=projectId,
            designation_id=designationId,
            team_id=teamId

        ).delete(
            synchronize_session=False
        )


        ProjectUserRole.query.filter_by(

            project_id=projectId,
            designation_id=designationId,
            team_id=teamId

        ).delete(
            synchronize_session=False
        )


        db.session.delete(pt)

        db.session.commit()

        return res(
            "Designation removed from project"
        )

    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            code=500
        )

# Get Roles by Project
def get_roles_by_project_code(projectCode):
    # Step 1: Get project using projectCode
    project = Project.query.filter_by(project_code=projectCode).first()

    if not project:
        return res("Project not found", [], 404)


    project_roles = ProjectUserRole.query.filter_by(project_id=project.id).all()


    # roleUserMap = [
    #     {
    #         "id": r.id,
    #         "userId": r.user_id,
    #         "userName": r.user.username if r.user else None,
    #         "loginUserName": r.user.login_username if r.user else None,
    #         "designationId": r.designation_id,
    #         "designationName": r.designation.name if r.designation else None,
    #         "teamId": r.team_id,
    #         "teamName":r.team.team_type
    #     }
    #     for r in project_roles
    # ]
    roleUserMap = []

    for r in project_roles:

        permissions = {}

        designation_permissions = (

            db.session.query(
                FeaturePage.page_code,
                PermissionAction.action_name,
                ProjectDesignationPermission.allowed
            )

            .join(
                FeaturePage,
                FeaturePage.id ==
                ProjectDesignationPermission.page_id
            )

            .join(
                PermissionAction,
                PermissionAction.id ==
                ProjectDesignationPermission.action_id
            )

            .filter(
                ProjectDesignationPermission.project_id
                == project.id,

                ProjectDesignationPermission
                .team_id
                == r.team_id,

                ProjectDesignationPermission
                .designation_id
                == r.designation_id
            )

            .all()
        )

        for p in designation_permissions:
            key = (
                f"{p.page_code}."
                f"{p.action_name}"
            )

            permissions[key] = (
                p.allowed
            )

        user_permissions = {}

        overrides = (

            db.session.query(
                FeaturePage.page_code,
                PermissionAction.action_name,
                ProjectUserPermission.allowed
            )

            .join(
                FeaturePage,
                FeaturePage.id ==
                ProjectUserPermission.page_id
            )

            .join(
                PermissionAction,
                PermissionAction.id ==
                ProjectUserPermission.action_id
            )

            .filter(
                ProjectUserPermission
                .project_user_role_id
                == r.id
            )

            .all()
        )

        for p in overrides:
            key = (
                f"{p.page_code}."
                f"{p.action_name}"
            )

            user_permissions[key] = (
                p.allowed
            )

        roleUserMap.append({

            "id": r.id,

            "userId":
                r.user_id,

            "userName":
                r.user.username
                if r.user else None,

            "loginUserName":
                r.user.login_username
                if r.user else None,

            "designationId":
                r.designation_id,

            "designationName":
                r.designation.name
                if r.designation
                else None,

            "teamId":
                r.team_id,

            "teamName":
                r.team.team_type,

            "permissions":
                permissions,

            "userPermissions":
                user_permissions

        })

    data=[ {
        "projectId": project.id,
        "projectCode": project.project_code,
        "projectName": project.project_name,
        "clientName": project.client_name,
        "roleUserMap": roleUserMap
    }]
    return res("Succesfully retrieved project roles", data=data,code=200)

def update_roles_by_project_code(projectCode, data):

    project = Project.query.filter_by(
        project_code=projectCode
    ).first()

    if not project:
        return res(
            "Project not found",
            [],
            404
        )

    role_user_map = data.get(
        "roleUserMap",
        []
    )

    if not role_user_map:
        return res(
            "roleUserMap is required",
            [],
            400
        )

    # FIX: load pages and actions once — used for O(1) lookup inside the loop
    # instead of querying DB per permission key (was causing 100s of DB hits).
    all_pages = {p.page_code: p for p in FeaturePage.query.all()}
    all_actions = {a.action_name: a for a in PermissionAction.query.all()}

    for item in role_user_map:

        designation_id = item.get(
            "designationId"
        )

        team_id = item.get(
            "teamId"
        )

        user_id = item.get(
            "userId"
        )

        # DEFAULT DESIGNATION PERMISSIONS
        permissions = item.get(
            "permissions",
            {}
        )

        # USER OVERRIDE
        user_permissions = item.get(
            "userPermissions",
            {}
        )

        # ==================================================
        # CREATE / UPDATE PROJECT USER ROLE
        # ==================================================

        role = ProjectUserRole.query.filter_by(
            project_id=project.id,
            designation_id=designation_id,
            team_id=team_id
        ).first()

        if role:

            role.user_id = user_id
            db.session.flush()

        else:

            role = ProjectUserRole(
                project_id=project.id,
                designation_id=designation_id,
                team_id=team_id,
                user_id=user_id
            )

            db.session.add(role)

            db.session.flush()

        # ==================================================
        # UPDATE PROJECT TEAM
        # ==================================================

        pt = ProjectTeam.query.filter_by(
            project_id=project.id,
            designation_id=designation_id,
            team_id=team_id
        ).first()

        if pt:
            pt.user_id = user_id

        # ==================================================
        # DESIGNATION PERMISSIONS
        # ==================================================

        # FIX: bulk delete ALL existing designation permissions for this
        # designation+team in ONE SQL DELETE instead of one delete per row.
        # Then we only INSERT the True ones below — False/None = not stored.
        ProjectDesignationPermission.query.filter_by(
            project_id=project.id,
            designation_id=designation_id,
            team_id=team_id
        ).delete(synchronize_session=False)

        for permission_key, allowed in permissions.items():

            try:
                page_code, action_name = permission_key.split(".")
            except ValueError:
                continue

            page = all_pages.get(page_code)
            if not page:
                continue

            action = all_actions.get(action_name)
            if not action:
                continue

            # None or False = deleted above, skip
            if allowed is None or allowed is False:

                # REMOVE CREATOR approval path if EDIT permission is removed
                if action_name == "EDIT":
                    approval = ApprovalPath.query.filter_by(
                        project_code=project.project_code,
                        module_code=page_code,
                        user_id=user_id,
                        path_type="CREATOR"
                    ).first()
                    if approval:
                        db.session.delete(approval)

                continue

            # allowed is True — INSERT only
            db.session.add(ProjectDesignationPermission(
                project_id=project.id,
                designation_id=designation_id,
                page_id=page.id,
                user_id=user_id,
                team_id=team_id,
                action_id=action.id,
                allowed=allowed
            ))

        # ==================================================
        # USER OVERRIDE PERMISSIONS
        # ==================================================

        # FIX: bulk delete ALL existing user override permissions for this
        # role in ONE SQL DELETE instead of one delete per row.
        # Then we only INSERT the True ones below — False/None = not stored.
        ProjectUserPermission.query.filter_by(
            project_user_role_id=role.id
        ).delete(synchronize_session=False)

        for permission_key, allowed in user_permissions.items():

            try:
                page_code, action_name = permission_key.split(".")
            except ValueError:
                continue

            page = all_pages.get(page_code)
            if not page:
                continue

            action = all_actions.get(action_name)
            if not action:
                continue

            # None or False = deleted above, skip
            if allowed is None or allowed is False:

                # REMOVE CREATOR approval path if EDIT permission is removed
                if action_name == "EDIT":
                    approval = ApprovalPath.query.filter_by(
                        project_code=project.project_code,
                        module_code=page_code,
                        user_id=user_id,
                        path_type="CREATOR"
                    ).first()
                    if approval:
                        db.session.delete(approval)

                continue

            # allowed is True — INSERT only
            db.session.add(ProjectUserPermission(
                project_user_role_id=role.id,
                page_id=page.id,
                action_id=action.id,
                allowed=allowed
            ))

    db.session.commit()

    response_data = [
        {
            "projectId": project.id
        }
    ]

    return res(
        "Roles and permissions updated successfully",
        response_data,
        200
    )


# Add Designation
# def add_designation(name): #Test done & pass
#     if Designation.query.filter_by(name=name).first():
#         return res("Designation already exists", code=400)
#
#     d = Designation(name=name)
#     db.session.add(d)
#     db.session.commit()
#
#     return res("Designation added", code=201)


def add_designation_to_project(request):
    data = request.get_json()

    designation_name = data.get("designationName")
    project_id = data.get("projectId")
    team_id = data.get("teamId")

    if not designation_name or not project_id or not team_id:
        return res("Missing required fields", code=400)

    # designation_name = designation_name.strip().lower()

    designation = Designation.query.filter_by(name=designation_name).first()

    if not designation:
        designation = Designation(name=designation_name)
        db.session.add(designation)
        db.session.flush()

    exists = ProjectTeam.query.filter_by(
        project_id=project_id,
        designation_id=designation.id,
        team_id=team_id
    ).first()

    if exists:
        return res("Designation already added in this team", code=400)

    # table 1
    pt = ProjectTeam(
        project_id=project_id,
        designation_id=designation.id,
        team_id=team_id,
        user_id=None
    )
    db.session.add(pt)

    # table 2
    pur = ProjectUserRole(
        user_id=None,
        project_id=project_id,
        designation_id=designation.id,
        team_id=team_id
    )
    db.session.add(pur)

    db.session.commit()

    team = Team.query.get(team_id)

    data = [{
        "designationName": designation.name,
        "designationId": designation.id,
        "teamId": team_id,
        "teamName": team.team_type if team else None
    }]

    return res("Designation added to project", data, code=201)


#  Get All Users
def get_all_users(projectCode=None):  # Test done & pass

    query = User.query.filter(
        User.is_active == True
    )

    if projectCode:

        query = (
            query
            .join(
                ProjectUserRole,
                ProjectUserRole.user_id == User.id
            )
            .join(
                Project,
                Project.id == ProjectUserRole.project_id
            )
            .filter(
                Project.project_code == projectCode
            )
            .distinct()
        )

    users = query.all()

    data = [{
        "id": u.id,
        "userName": u.username,
        "empCode": u.emp_code,
        "loginUserName": u.login_username,
        "email": u.email,
        "mobile": u.mobile,
        "whatsapp": u.wp_mobile,
        "role": u.global_role.name if u.global_role else None,
        "status": u.is_active
    } for u in users]
    return data




def get_all_project(exclude_current: bool = False, current_project_code: str = None):
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    role = claims.get("role")

    if exclude_current:
        # No role restriction — all projects, minus the current one
        query = Project.query
        if current_project_code:
            query = query.filter(Project.project_code != current_project_code)
        projects = query.all()

    else:
        if role == "super_admin":
            projects = Project.query.all()
        else:
            projects = (
                db.session.query(Project)
                .join(ProjectTeam, Project.id == ProjectTeam.project_id)
                .filter(ProjectTeam.user_id == user_id)
                .distinct()
                .all()
            )

    if not projects:
        return res("No projects found", [], 404)
    data = [
        {
        "id": p.id,
        "projectCode": p.project_code,
        "projectName": p.project_name,
        "clientName": p.client_name,
        # "projectDetails": p.project_details,
        # "registeredAddress": p.registered_address,
        #
        # "projectManagementContact": p.proj_mgmt_contact_number,
        # "projectManagementEmail": p.proj_mgmt_email_id,
        #
        # "commercialManager": p.commercial_manager,
        # "commercialEmail": p.comm_mgmt_email_id,
        # "commercialContact": p.comm_mgmt_contact_number,

        "gstn": p.gstn,
        "state": p.state,
        # "stateCode": p.state_code,
        #
        # "billingAddress": p.billing_address,
        # "shippingAddress1": p.shipping_address,
        # "shippingAddress2": p.shipping_address_2,
        # "shippingAddress3": p.shipping_address_3,
        #
        # "projectManager": p.project_manager,
        #
        # "initialOrderValue": p.initial_order_value,
        # "revisedOrderValue": p.revised_order_value,
        #
        # "scheduleDate": p.schedule_date.isoformat() if p.schedule_date else None,
        # "scheduleCompletionDate": p.schedule_completion_date.isoformat() if p.schedule_completion_date else None,
        #
        # "originalStartDate": p.original_start_date.isoformat() if p.original_start_date else None,
        # "extendedCompleteDate": p.extended_complete_date.isoformat() if p.extended_complete_date else None,

        "status": p.status
        }
        for p in projects
    ]

    return res("Projects Fetched", data, 200)

def get_project_team(projectId):
    teams = ProjectTeam.query.filter_by(project_id=projectId).all()

    data = [
        {
            "id": t.id,
            "designationId": t.designation_id,
            "designationName": t.designation.name if t.designation else None,
            "teamId": t.team_id,
            "teamName": t.team.team_type if t.team else None,
            "userId": t.user_id,
            "userName": t.user.username if t.user else None
        }
        for t in teams
    ]

    return res("Project team fetched", data, 200)


def get_project_by_id(projectId):
    project = Project.query.get(projectId)

    if not project:
        return res("Project not found", code=404)

    data = [{
        "id": project.id,
        "projectCode": project.project_code,
        "projectName": project.project_name,
        "clientName": project.client_name,
        "projectDetails": project.project_details,
        "registeredAddress": project.registered_address,

        "projMgmtContactNumber": project.proj_mgmt_contact_number,
        "projMgmtEmailId": project.proj_mgmt_email_id,

        "commercialManager": project.commercial_manager,
        "commMgmtEmailId": project.comm_mgmt_email_id,
        "commMgmtContactNumber": project.comm_mgmt_contact_number,

        "gstn": project.gstn,
        "state": project.state,
        "stateCode": project.state_code,

        "billingAddress": project.billing_address,
        "shippingAddress": project.shipping_address,
        "shippingAddress2": project.shipping_address_2,
        "shippingAddress3": project.shipping_address_3,

        "projectManager": project.project_manager,

        "initialOrderValue": project.initial_order_value,
        "revisedOrderValue": project.revised_order_value,

        "scheduleDate": project.schedule_date.isoformat() if project.schedule_date else None,
        "scheduleCompletionDate": project.schedule_completion_date.isoformat() if project.schedule_completion_date else None,

        "originalStartDate": project.original_start_date.isoformat() if project.original_start_date else None,
        "extendedCompleteDate": project.extended_complete_date.isoformat() if project.extended_complete_date else None,

        "status": project.status
    }]

    return res("Project fetched", data)

def update_project(projectId, data):
    try:
        project = Project.query.get(projectId)

        if not project:
            return res("Project not found", code=404)

        # 🔹 Optional: prevent duplicate project code
        project_code = data.get("projectCode")
        if project_code and project_code != project.project_code:
            existing = Project.query.filter_by(project_code=project_code).first()
            if existing:
                return res("Project code already exists", code=400)
            project.project_code = project_code

        # 🔹 Validate status
        status = data.get("status")
        if status and status not in ["ongoing", "hold", "completed"]:
            return res("Invalid status", code=400)

        # 🔹 Update fields (only if provided)
        project.project_name = data.get("projectName", project.project_name)
        project.client_name = data.get("clientName", project.client_name)
        project.project_details = data.get("projectDetails", project.project_details)
        project.registered_address = data.get("registeredAddress", project.registered_address)
        project.proj_mgmt_contact_number = data.get("projMgmtContactNumber", project.proj_mgmt_contact_number)
        project.proj_mgmt_email_id = data.get("projMgmtEmailId", project.proj_mgmt_email_id)
        project.commercial_manager = data.get("commercialManager", project.commercial_manager)
        project.comm_mgmt_email_id = data.get("commMgmtEmailId", project.comm_mgmt_email_id)
        project.comm_mgmt_contact_number = data.get("commMgmtContactNumber", project.comm_mgmt_contact_number)
        project.gstn = data.get("gstn", project.gstn)
        project.billing_address = data.get("billingAddress", project.billing_address)
        project.shipping_address = data.get("shippingAddress", project.shipping_address)
        project.shipping_address_2 = data.get("shippingAddress2", project.shipping_address_2)
        project.shipping_address_3 = data.get("shippingAddress3", project.shipping_address_3)
        project.project_manager = data.get("projectManager", project.project_manager)
        project.initial_order_value = data.get("initialOrderValue", project.initial_order_value)
        project.revised_order_value = data.get("revisedOrderValue", project.revised_order_value)
        project.state = data.get("state", project.state)
        project.state_code = data.get("stateCode", project.state_code)
        project.status = status if status else project.status

        # 🔹 Date fields
        if data.get("scheduleDate"):
            project.schedule_date = parse_date(data.get("scheduleDate"))

        if data.get("scheduleCompletionDate"):
            project.schedule_completion_date = parse_date(data.get("scheduleCompletionDate"))

        if data.get("originalStartDate"):
            project.original_start_date = parse_date(data.get("originalStartDate"))

        if data.get("extendedCompleteDate"):
            project.extended_complete_date = parse_date(data.get("extendedCompleteDate"))

        db.session.commit()

        data = [{
            "projectId": project.id,
            "projectCode": project.project_code,
            "projectName": project.project_name
        }]

        return res("Project updated successfully", data, 200)

    except Exception as e:
        db.session.rollback()
        print("ERROR:", str(e))
        return res("Internal server error", code=500)

def get_user_by_id(userId):
    user = User.query.get(userId)

    if not user:
        return res("User not found",[], code=200)

    # base_url = request.host_url
    data =[{
        "id": user.id,
        "username": user.username,
        "employeeCode": user.emp_code,
        "loginUserName": user.login_username,
        "email": user.email,
        "mobile": user.mobile,
        "whatsapp": user.wp_mobile,
        "role": user.global_role.name if user.global_role else None,
        "status": user.is_active,
        "password": "",
        "signatureUrl": user.signature

    }]

    return res("User fetched", data,200)


def update_user(userId, request):
    user = User.query.get(userId)

    if not user:
        return res("User not found", code=404)

    username = request.form.get("username")
    password = request.form.get("password")
    role_name = request.form.get("role")
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    wp_mobile = request.form.get("whatsapp")
    emp_code = request.form.get("employeeCode")
    is_active = request.form.get("status")

    # update fields
    user.username = username or user.username
    user.email = email or user.email
    user.mobile = mobile or user.mobile
    user.wp_mobile = wp_mobile or user.wp_mobile
    user.emp_code = emp_code or user.emp_code


    # update role
    if role_name:
        role = Role.query.filter_by(name=role_name).first()
        if role:
            user.global_role = role

    if is_active is not None:
        user.is_active = str(is_active).lower() in ["true", "1", "yes"]

    # password update
    if password:
        user.set_password(password)

    # file upload
    base_url = request.host_url
    file = request.files.get("signature")
    if file:
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)

        ext = file.filename.split('.')[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        file.save(filepath)
        user.signature = filename

    db.session.commit()

    data = [{
        "id": user.id,
        "username": user.username,
        "employeeCode": user.emp_code,
        "loginUserName": user.login_username,
        "email": user.email,
        "mobile": user.mobile,
        "whatsapp": user.wp_mobile,
        "role": user.global_role.name if user.global_role else None,
        "status": user.is_active,
        "signatureUrl": f"{base_url}/setting/uploads/signatures/{user.signature}"
    }]

    return res("User updated successfully", data, 200)







def create_approval_path(data):

    try:

        project_code = data.get(
            "projectCode"
        )

        modules = data.get(
            "modules"
        ) or []


        if not project_code:

            return res(
                "Project code required",
                [],
                400
            )


        if not modules:

            return res(
                "Modules required",
                [],
                400
            )


        for module in modules:

            module_code = module.get(
                "moduleCode"
            )

            creator_users = (
                module.get(
                    "creatorUsers"
                ) or []
            )

            approver_users = (
                module.get(
                    "approverUsers"
                ) or []
            )


            if not module_code:

                continue


            # delete old mappings
            ApprovalPath.query.filter(

                ApprovalPath.project_code
                == project_code,

                ApprovalPath.module_code
                == module_code

            ).delete(
                synchronize_session=False
            )


            # ------------------
            # creators
            # ------------------

            for item in creator_users:

                user_id = item.get(
                    "userId"
                )

                if not user_id:

                    continue


                db.session.add(

                    ApprovalPath(

                        project_code=
                        project_code,

                        module_code=
                        module_code,

                        user_id=
                        user_id,

                        level_no=0,

                        path_type=
                        "CREATOR"

                    )

                )


            # ------------------
            # approvers
            # ------------------

            for item in approver_users:

                user_id = item.get(
                    "userId"
                )

                level_no = item.get(
                    "level"
                )


                if (
                    not user_id
                    or
                    level_no is None
                ):

                    continue


                db.session.add(

                    ApprovalPath(

                        project_code=
                        project_code,

                        module_code=
                        module_code,

                        user_id=
                        user_id,

                        level_no=
                        level_no,

                        path_type=
                        "APPROVER"

                    )

                )


        db.session.commit()


        # return in your existing
        # [data] format

        return get_approval_paths(
            project_code
        )


    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )




# def get_approval_paths(projectCode):
#
#     try:
#
#         if not projectCode:
#
#             return res(
#                 "Project code required",
#                 [],
#                 400
#             )
#
#
#         rows = (
#             ApprovalPath.query
#             .filter_by(
#                 project_code=projectCode
#             )
#             .order_by(
#                 ApprovalPath.module_code,
#                 ApprovalPath.level_no
#             )
#             .all()
#         )
#
#
#         module_map = defaultdict(
#
#             lambda: {
#
#                 "moduleCode": None,
#                 "moduleName": None,
#
#                 "creatorUsers": [],
#                 "approverUsers": []
#
#             }
#
#         )
#
#
#         for row in rows:
#
#             item = module_map[
#                 row.module_code
#             ]
#
#             item["moduleCode"] = row.module_code
#
#             item["moduleName"] = (
#                 row.module.module_name
#                 if row.module
#                 else None
#             )
#
#
#             if row.path_type=="CREATOR":
#
#                 item[
#                     "creatorUsers"
#                 ].append({
#
#                     "userId":
#                     row.user_id,
#
#                     "userName":
#                     row.user.username
#                     if row.user
#                     else None
#
#                 })
#
#
#             elif row.path_type=="APPROVER":
#
#                 item[
#                     "approverUsers"
#                 ].append({
#
#                     "userId":
#                     row.user_id,
#
#                     "userName":
#                     row.user.username
#                     if row.user
#                     else None,
#
#                     "level":
#                     row.level_no
#
#                 })
#
#
#         data = {
#
#             "projectCode":
#             projectCode,
#
#             "modules":
#             list(
#                 module_map.values()
#             )
#
#         }
#
#
#         return res(
#             "Approval path fetched successfully",
#             [data],
#             200
#         )
#
#
#     except Exception as e:
#
#         return res(
#             str(e),
#             [],
#             500
#         )


#######test

from collections import defaultdict
from sqlalchemy.orm import joinedload

def get_approval_paths(projectCode):
    try:
        if not projectCode:
            return res("Project code required", [], 400)

        rows = (
            ApprovalPath.query
            .filter_by(project_code=projectCode)
            .options(
                joinedload(ApprovalPath.module),
                joinedload(ApprovalPath.user)
            )
            .order_by(
                ApprovalPath.module_code,
                ApprovalPath.level_no
            )
            .all()
        )

        module_map = defaultdict(
            lambda: {
                "moduleCode": None,
                "moduleName": None,
                "creatorUsers": [],
                "approverUsers": []
            }
        )

        for row in rows:
            item = module_map[row.module_code]
            item["moduleCode"] = row.module_code
            item["moduleName"] = row.module.module_name if row.module else None

            if row.path_type == "CREATOR":
                item["creatorUsers"].append({
                    "userId": row.user_id,
                    "userName": row.user.username if row.user else None
                })

            elif row.path_type == "APPROVER":
                item["approverUsers"].append({
                    "userId": row.user_id,
                    "userName": row.user.username if row.user else None,
                    "level": row.level_no
                })

        data = {
            "projectCode": projectCode,
            "modules": list(module_map.values())
        }

        return res("Approval path fetched successfully", [data], 200)

    except Exception as e:
        return res(str(e), [], 500)







def get_edit_users(
        project_code
):

    try:

        project = Project.query.filter_by(
            project_code=project_code
        ).first()

        if not project:

            return res(
                "Project not found",
                [],
                404
            )

        result = {}

        roles = (

            db.session.query(

                ProjectUserRole,

                User.id,

                User.username,

                User.login_username

            )

            .join(

                User,

                User.id
                ==
                ProjectUserRole.user_id

            )

            .filter(

                ProjectUserRole.project_id
                == project.id

            )

            .all()
        )

        permissions = (

            db.session.query(

                ProjectDesignationPermission.designation_id,

                ProjectDesignationPermission.team_id,

                FeaturePage.page_code

            )

            .join(
                FeaturePage,
                FeaturePage.id
                ==
                ProjectDesignationPermission.page_id
            )

            .join(
                PermissionAction,
                PermissionAction.id
                ==
                ProjectDesignationPermission.action_id
            )

            .filter(

                ProjectDesignationPermission.project_id
                == project.id,

                PermissionAction.action_name
                == "EDIT"

            )

            .all()
        )

        permission_map = {

            (
                p.designation_id,
                p.team_id,
                p.page_code
            ): True

            for p in permissions
        }

        pages=[

            "indent",
            "enquiry",
            "order",
            "goods_received_note",
            "goods_issue_note",
            "labour_id",
            "dlr_entry",
            "dlr_report",
            "log_sheet",
            "machinery_stock_summary",
            "monthly_rent",
            "billing_by_grn",
            "billing_by_srn",
            "indent_allocation",
            "asset_id",
            "asset_report",
            "order_boq",
            "budget_costing",
            "monthly_planning",
            "daily_progress_report",
            "reconciliation",
            "certified_bill",
            "hold_amend_pending",
            "work_in_progress",
            "drawing_register",
            "bbs_register",
            "concrete_register",
            "hindrance_register",
            "sale",
            "purchases",
            "receipt",
            "payment",
            "contra",
            "debit_note",
            "credit_note",
            "journal"
        ]

        for page in pages:
            result[f"{page}.EDIT"] = []

        for role, user_id, username, login_username in roles:

            for designation_id, team_id, page in permission_map.keys():

                if (

                        designation_id
                        == role.designation_id

                        and

                        team_id
                        == role.team_id
                ):
                    key = f"{page}.EDIT"

                    if key not in result:
                        result[key] = []

                    result[key].append({

                        "id":
                            user_id,

                        "userName":
                            username,

                        "userDisplayName":
                            login_username
                    })

        return res(
            "success",
            result
        )

    except Exception as e:

        return res(
            str(e),
            [],
            500
        )


def create_project_location(request):

    body = request.get_json()

    project_code = body.get("projectCode")
    store_location = body.get("storeLocation")
    use_location = body.get("useLocation")

    project = (
        Project.query
        .filter_by(
            project_code=project_code
        )
        .first()
    )

    if not project:
        return res(
            "Project not found",
            [],
            404
        )

    location = ProjectLocation(
        project_code=project_code,
        store_location=store_location,
        use_location=use_location
    )

    db.session.add(location)
    db.session.commit()

    data = [{
        "id": location.id,
        "projectCode": location.project_code,
        "storeLocation": location.store_location,
        "useLocation": location.use_location
    }]

    return res(
        "Location created",
        data,
        200
    )

def update_project_location(
        request,
        location_id
):

    location = (
        ProjectLocation.query
        .get(location_id)
    )

    if not location:
        return res(
            "Location not found",
            [],
            404
        )

    body = request.get_json()

    location.store_location = body.get(
        "storeLocation",
        location.store_location
    )

    location.use_location = body.get(
        "useLocation",
        location.use_location
    )

    db.session.commit()

    data = [{
        "id": location.id,
        "projectCode": location.project_code,
        "storeLocation": location.store_location,
        "useLocation": location.use_location
    }]

    return res(
        "Location updated",
        data,
        200
    )

def get_project_locations(project_code):

    project = (
        Project.query
        .filter_by(
            project_code=project_code
        )
        .first()
    )

    if not project:
        return res(
            "Project not found",
            [],
            404
        )

    data = []

    for location in project.projects:

        data.append({
            "id": location.id,
            "projectCode": location.project_code,
            "storeLocation": location.store_location,
            "useLocation": location.use_location
        })

    return res(
        "Location list fetched",
        data,
        200
    )

def delete_project_location(location_id):

    location = (
        ProjectLocation.query
        .get(location_id)
    )

    if not location:
        return res(
            "Location not found",
            [],
            404
        )

    data = [{
        "id": location.id,
        "projectCode": location.project_code,
        "storeLocation": location.store_location,
        "useLocation": location.use_location
    }]

    db.session.delete(location)
    db.session.commit()

    return res(
        "Location deleted successfully",
        data,
        200
    )