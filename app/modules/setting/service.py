# app/modules/setting/service.py
import os
import uuid
from flask import request
from datetime import datetime
from app.models.user import User
from app.models.role import Role
from app.models.project import Project
from app.models.team import ProjectTeam
from app.models.project_role import ProjectUserRole
from app.models.designation import Designation
from app.extensions import db
from app.response import res

UPLOAD_FOLDER = "uploads/signatures"
def create_user(request): # Test done & pass
    # print("FORM:", request.form)
    # print("FILES:", request.files)
    #
    # role_name = request.form.get("role")
    #
    # print("ROLE:", role_name)
    # form data
    username = request.form.get("username")
    password = request.form.get("password")
    role_name = request.form.get("role")
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    wp_mobile = request.form.get("wp_mobile")
    emp_code = request.form.get("emp_code")

    # file
    file = request.files.get("signature")

    # role check
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return res("Role not found", code=404)

    # create user
    user = User(
        username=username,
        email=email,
        mobile=mobile,
        wp_mobile=wp_mobile,
        emp_code=emp_code,
        global_role=role
    )
    user.set_password(password)

    # save signature file
    if file:
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)

        ext = file.filename.split('.')[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        file.save(filepath)

        user.signature = filepath  # store path

    db.session.add(user)
    db.session.commit()

    return res("User created", code=201)

def parse_date(date_str): #Test done & pass
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    except:
        return None


def create_project(data): #Test done & pass
    try:
        # Required fields
        project_code = data.get("ProjectCode")
        project_name = data.get("ProjectName")

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
            client_name=data.get("ClientName"),
            project_details=data.get("ProjectDetails"),
            registered_address=data.get("RegisteredAddress"),
            proj_mgmt_contact_number=data.get("proj_mgmt_contact_number"),
            proj_mgmt_email_id=data.get("proj_mgmt_email_id"),
            commercial_manager=data.get("CommercialManager"),
            comm_mgmt_email_id=data.get("comm_mgmt_email_id"),
            comm_mgmt_contact_number=data.get("comm_mgmt_contact_number"),
            gstn=data.get("Gstn"),
            billing_address=data.get("BillingAddress"),
            shipping_address=data.get("ShippingAddress"),
            shipping_address_2=data.get("ShippingAddress_2"),
            shipping_address_3=data.get("ShippingAddress_3"),
            project_manager=data.get("ProjectManager"),
            initial_order_value=data.get("InitialOrderValue"),
            revised_order_value=data.get("RevisedOrderValue"),
            status=status,

            #  Date fields
            schedule_date=parse_date(data.get("ScheduleDate")),
            schedule_completion_date=parse_date(data.get("ScheduleCompletionDate")),
            original_start_date=parse_date(data.get("OriginalStartDate")),
            extended_complete_date=parse_date(data.get("ExtendedCompleteDate")),
        )

        #  Save
        db.session.add(project)
        db.session.commit()

        return res(
            "Project created",
            data={
                "ProjectId": project.id,
                "ProjectCode": project.project_code
            },
            code=201
        )

    except Exception as e:
        db.session.rollback()
        print("ERROR:", str(e))
        return res("Internal server error", code=500)

#Assign Role
def assign_role(ProjectId, DesignationId, TeamId, user_id=None): #Test done & pass

    team = ProjectTeam.query.get(TeamId)
    if not team or team.project_id != ProjectId:
        return res("Invalid team for this project", code=400)

    existing = ProjectUserRole.query.filter_by(
        user_id=user_id,
        project_id=ProjectId,
        designation_id=DesignationId,
        team_id=TeamId
    ).first()

    if existing:
        return res("Already exists", code=400)

    role = ProjectUserRole(
        user_id=user_id,  # can be NULL
        project_id=ProjectId,
        designation_id=DesignationId,
        team_id=TeamId
    )

    db.session.add(role)
    db.session.commit()

    return res("Role added", code=201)

# Update Role
def update_role(RoleId, user_id=None, DesignationId=None):
    role = ProjectUserRole.query.get(RoleId)

    if not role:
        return res("Role not found", code=404)

    # NULL assignment
    if user_id is not None:
        role.user_id = user_id

    if DesignationId:
        role.designation_id = DesignationId

    db.session.commit()

    return res("Role updated")


# Delete Role
def delete_role(RoleId):
    role = ProjectUserRole.query.get(RoleId)

    if not role:
        return res("Role not found", code=404)

    db.session.delete(role)
    db.session.commit()

    return res("Role deleted successfully")

# Delete Designation
def delete_project_designation(ProjectId, TeamId, DesignationId):

    roles = ProjectUserRole.query.filter_by(
        project_id=ProjectId,
        team_id=TeamId,
        designation_id=DesignationId
    ).all()

    if not roles:
        return res("Designation not found in this project", code=404)

    for r in roles:
        db.session.delete(r)

    db.session.commit()

    return res("Designation removed from project")

# Get Roles by Project
def get_roles_by_project(ProjectId): #Test done & pass
    roles = ProjectUserRole.query.filter_by(project_id=ProjectId).all()

    data = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "user_name": r.user.username if r.user else None,
            "DesignationId": r.designation_id,
            "DesignationName": r.designation.name if r.designation else None,
            "TeamId": r.team_id
        }
        for r in roles
    ]
    return res("", data)


# Add Designation
def add_designation(name): #Test done & pass
    if Designation.query.filter_by(name=name).first():
        return res("Designation already exists", code=400)

    d = Designation(name=name)
    db.session.add(d)
    db.session.commit()

    return res("Designation added", code=201)


#  Get All Users
def get_all_users(): #Test done & pass
    users = User.query.filter_by(is_active=True).all()

    data = [{"id": u.id, "name": u.username} for u in users]

    return res("", data)


# Get All Designations
def get_all_designations(): #Test done & pass
    roles = Designation.query.all()

    data = [{"id": r.id, "name": r.name} for r in roles]

    return res("", data)