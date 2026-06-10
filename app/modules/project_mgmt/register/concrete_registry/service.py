from datetime import datetime, date, time

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.response import res
from app.models.project import Project
from app.cloudinary_uploader import upload_file_to_bunny
from app.models.concrete_registry import ConcreteRegistry
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
)


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, time):
        return d.strftime("%H:%M:%S")
    return d


def _registry_dict(r):
    return {
        "id": r.id,
        "projectCode": r.projectcode,
        "referenceOrderNo": r.reference_order_no,
        "projectSubLocation": r.project_sub_location,
        "segment": r.segment,
        "pouringDate": _fmt_date(r.pouring_date),
        "pouringStartDate": _fmt_date(r.pouring_start_date),
        "pouringEndDate": _fmt_date(r.pouring_end_date),
        "gradeConcrete": r.grade_concrete,
        "concreteVolume": r.concrete_volume,
        "requisitionNo": r.requisition_no,
        "requisitionBy": r.requisition_by,
        "vehicleNumber": r.vehicle_number,
        "batchNo": r.batch_no,
        "attachBatchFile": r.attach_batch_file,
        "workflowStatus": r.workflow_status,
        "status": r.status,
        "currentLevel": r.current_level,
        "locked": r.locked,
    }


def generate_reg_no(project_code):
    last_reg = (
        db.session.query(ConcreteRegistry.reference_order_no)
        .filter(ConcreteRegistry.projectcode == project_code)
        .order_by(ConcreteRegistry.id.desc())
        .first()
    )

    if last_reg:
        try:
            last_serial = int(last_reg[0][2:])
        except (ValueError, TypeError):
            last_serial = 0
    else:
        last_serial = 0

    return f"71{last_serial + 1:04d}"


def create_resigistry(request, user_id=None):
    data = request.form
    file = request.files
    try:
        pc = data.get("projectCode")
        project = Project.query.filter_by(project_code=pc).first()
        if not project:
            return res("Invalid Project Code", [], 400)

        allowed = is_creator(pc, "concrete_registry", user_id)
        if not allowed:
            return res("You are not Concrete Registry creator", [], 403)

        xtmp = generate_reg_no(pc)
        attach_file = file.get("attachBatchFile")
        batch_file = upload_file_to_bunny(
            file=attach_file,
            mainFolder="concrete_registry",
            subFolder=xtmp,
            fileName="attach_file"
        )

        registry = ConcreteRegistry(
            projectcode=pc,
            reference_order_no=xtmp,
            project_sub_location=data.get("projectSubLocation"),
            segment=data.get("segment"),
            pouring_date=data.get("pouringDate"),
            pouring_start_date=data.get("pouringStartDate"),
            pouring_end_date=data.get("pouringEndDate"),
            grade_concrete=data.get("gradeConcrete"),
            concrete_volume=data.get("concreteVolume"),
            attach_batch_file=batch_file,
            requisition_no=data.get("requisitionNo"),
            requisition_by=data.get("requisitionBy"),
            vehicle_number=data.get("vehicleNumber"),
            batch_no=data.get("batchNo"),
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(registry)
        db.session.commit()

        return res("Concrete Registry created", [_registry_dict(registry)], 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def get_registry_list(request):
    try:
        project_code = request.args.get("projectCode")
        query = ConcreteRegistry.query
        if project_code:
            query = query.filter_by(projectcode=project_code)
        registries = query.order_by(ConcreteRegistry.id.desc()).all()
        data = [_registry_dict(r) for r in registries]
        return res("Concrete Registry list", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


def get_registry_by_id(registry_id):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)
        return res("Concrete Registry details", [_registry_dict(registry)], 200)
    except Exception as e:
        return res(str(e), [], 500)


def update_registry(registry_id, request, user_id=None):
    data = request.form
    file = request.files
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if registry.locked:
            return res("Concrete Registry cannot be edited", [], 400)

        if registry.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(registry.projectcode, "concrete_registry", user_id)
        if not allowed:
            return res("You are not Concrete Registry creator", [], 403)

        if data.get("projectSubLocation"):
            registry.project_sub_location = data.get("projectSubLocation")
        if data.get("segment"):
            registry.segment = data.get("segment")
        if data.get("pouringDate"):
            registry.pouring_date = data.get("pouringDate")
        if data.get("pouringStartDate"):
            registry.pouring_start_date = data.get("pouringStartDate")
        if data.get("pouringEndDate"):
            registry.pouring_end_date = data.get("pouringEndDate")
        if data.get("gradeConcrete"):
            registry.grade_concrete = data.get("gradeConcrete")
        if data.get("concreteVolume"):
            registry.concrete_volume = data.get("concreteVolume")
        if data.get("requisitionNo"):
            registry.requisition_no = data.get("requisitionNo")
        if data.get("requisitionBy"):
            registry.requisition_by = data.get("requisitionBy")
        if data.get("vehicleNumber"):
            registry.vehicle_number = data.get("vehicleNumber")
        if data.get("batchNo"):
            registry.batch_no = data.get("batchNo")

        attach_file = file.get("attachBatchFile")
        if attach_file:
            batch_file = upload_file_to_bunny(
                file=attach_file,
                mainFolder="concrete_registry",
                subFolder=registry.reference_order_no,
                fileName="attach_file"
            )
            registry.attach_batch_file = batch_file

        if registry.workflow_status == "Reback":
            registry.correction_sent_at = None

        registry.updated_by = user_id
        registry.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Concrete Registry updated", [_registry_dict(registry)], 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_registry(registry_id, submitted_by=None):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if registry.workflow_status not in ["Draft", "Reback"]:
            return res("Concrete Registry already submitted", [], 400)

        if registry.workflow_status == "Reback":
            registry.current_level = 0

        first_level = get_first_approver(registry.projectcode, "concrete_registry")

        if not first_level:
            registry.workflow_status = "Approved"
            registry.locked = True
            registry.approved_by = submitted_by
            registry.submitted_at = datetime.utcnow()
            registry.final_approved_at = datetime.utcnow()
        else:
            registry.workflow_status = f"Pending_L{first_level.level_no}"
            registry.current_level = first_level.level_no
            registry.locked = True
            registry.submitted_at = datetime.utcnow()

        create_history(
            project_code=registry.projectcode,
            module_code="concrete_registry",
            record_id=registry.id,
            level_no=registry.current_level,
            action="SUBMIT",
            action_by=submitted_by
        )

        registry.submitted_by = submitted_by
        registry.updated_by = submitted_by
        registry.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Concrete Registry submitted successfully",
            {
                "id": registry.id,
                "referenceOrderNo": registry.reference_order_no,
                "workflowStatus": registry.workflow_status
            },
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_registry(registry_id, approved_by=None, comments=None):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if not registry.workflow_status.startswith("Pending"):
            return res("Concrete Registry not pending", [], 400)

        allowed = is_current_approver(
            registry.projectcode,
            "concrete_registry",
            registry.current_level,
            approved_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            registry.projectcode,
            "concrete_registry",
            registry.current_level
        )

        if next_level:
            create_history(
                project_code=registry.projectcode,
                module_code="concrete_registry",
                record_id=registry.id,
                level_no=registry.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments
            )
            registry.current_level = next_level.level_no
            registry.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=registry.projectcode,
                module_code="concrete_registry",
                record_id=registry.id,
                level_no=registry.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments
            )
            registry.workflow_status = "Approved"
            registry.locked = True
            registry.approved_by = approved_by
            registry.final_approved_at = datetime.utcnow()

        registry.updated_by = approved_by
        registry.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Concrete Registry approved successfully",
            {
                "id": registry.id,
                "workflowStatus": registry.workflow_status,
                "currentLevel": registry.current_level
            },
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# REBACK
# ══════════════════════════════════════════════════════════════════

def reback_registry(registry_id, reback_by=None, comments=None):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if not registry.workflow_status.startswith("Pending"):
            return res("Concrete Registry not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            registry.projectcode,
            "concrete_registry",
            registry.current_level,
            reback_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        registry.workflow_status = "Reback"
        registry.locked = False
        registry.correction_sent_at = datetime.utcnow()
        registry.updated_by = reback_by
        registry.updated_at = datetime.utcnow()

        create_history(
            project_code=registry.projectcode,
            module_code="concrete_registry",
            record_id=registry.id,
            level_no=registry.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "Concrete Registry sent for correction",
            {"id": registry.id, "workflowStatus": registry.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# REJECT
# ══════════════════════════════════════════════════════════════════

def reject_registry(registry_id, rejected_by=None, comments=None):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if not registry.workflow_status.startswith("Pending"):
            return res("Concrete Registry not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            registry.projectcode,
            "concrete_registry",
            registry.current_level,
            rejected_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        registry.workflow_status = "Rejected"
        registry.locked = True
        registry.rejected_at = datetime.utcnow()
        registry.rejected_by = rejected_by
        registry.status = "Inactive"
        registry.updated_by = rejected_by
        registry.updated_at = datetime.utcnow()

        create_history(
            project_code=registry.projectcode,
            module_code="concrete_registry",
            record_id=registry.id,
            level_no=registry.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "Concrete Registry rejected",
            {"id": registry.id, "workflowStatus": registry.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# HISTORY
# ══════════════════════════════════════════════════════════════════

def get_registry_history(registry_id):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        rows = get_history("concrete_registry", registry.id)

        data = []
        for row in rows:
            data.append({
                "id": row.id,
                "action": row.action,
                "level": row.level_no,
                "comments": row.comments,
                "actionBy": row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("Concrete Registry history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
