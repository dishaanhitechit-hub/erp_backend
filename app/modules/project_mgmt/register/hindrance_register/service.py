import uuid as _uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.hindranceRegister import HindranceRegister
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

MODULE_CODE = "hindrance_register"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _generate_hindrance_no():
    db.session.execute(text("SELECT pg_advisory_xact_lock(480000)"))
    last = (
        db.session.query(HindranceRegister.hindrance_no)
        .order_by(HindranceRegister.id.desc())
        .first()
    )
    if not last:
        return "HIN001"
    suffix = last[0][3:]   # strip "HIN"
    next_num = int(suffix) + 1
    return "HIN" + str(next_num).zfill(len(suffix))


def _calc_total(manpower, plant_machinery, materials):
    return (
        float(manpower or 0) +
        float(plant_machinery or 0) +
        float(materials or 0)
    )


def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def _serialise(h):
    return {
        "id":                    h.id,
        "hindranceNo":           h.hindrance_no,
        "uuid":                  h.hindrance_uuid,
        "projectCode":           h.project_code,
        "projectName":           h.project.project_name if h.project else None,
        "hindranceDate":         _fmt_date(h.hindrance_date),
        "titleOfHindrance":      h.title_of_hindrance,
        "causeOfHindrance":      h.cause_of_hindrance,
        "manpowerDetails":       h.manpower_details,
        "manpowerAmount":        float(h.manpower_amount or 0),
        "plantMachineryDetails": h.plant_machinery_details,
        "plantMachineryAmount":  float(h.plant_machinery_amount or 0),
        "materialsDetails":      h.materials_details,
        "materialsAmount":       float(h.materials_amount or 0),
        "totalEffectedAmount":   float(h.total_effected_amount or 0),
        "attachment":            h.attachment,
        "intimationTo":          h.intimation_to,
        "intimationVia":         h.intimation_via,
        "workflowStatus":        h.workflow_status,
        "status":                h.status,
        "currentLevel":          h.current_level,
        "locked":                h.locked,
        "createdBy":             h.creator.username if h.creator else None,
        "createdAt":             h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else None,
        "approvedBy":            h.approver.username if h.approver else None,
        "finalApprovedAt":       h.final_approved_at.strftime("%Y-%m-%d %H:%M:%S") if h.final_approved_at else None,
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_hindrance_register(data, user_id, files=None):
    project_code = data.get("projectCode")

    if not project_code:
        return res("projectCode required", [], 400)

    if not is_creator(project_code, MODULE_CODE, user_id):
        return res("You are not a Hindrance Register creator", [], 403)

    try:
        new_uuid = str(_uuid.uuid4())
        hindrance_no = _generate_hindrance_no()

        manpower_amount       = float(data.get("manpowerAmount") or 0)
        plant_machinery_amount = float(data.get("plantMachineryAmount") or 0)
        materials_amount      = float(data.get("materialsAmount") or 0)
        total                 = _calc_total(manpower_amount, plant_machinery_amount, materials_amount)

        attachment = None
        if files:
            att_file = files.get("attachment")
            if att_file:
                attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="hindrance_register",
                    subFolder=hindrance_no,
                    fileName="attachment"
                )

        hr = HindranceRegister(
            hindrance_no=hindrance_no,
            hindrance_uuid=new_uuid,
            project_code=project_code,
            hindrance_date=data.get("hindranceDate") or None,
            title_of_hindrance=data.get("titleOfHindrance"),
            cause_of_hindrance=data.get("causeOfHindrance"),
            manpower_details=data.get("manpowerDetails"),
            manpower_amount=manpower_amount,
            plant_machinery_details=data.get("plantMachineryDetails"),
            plant_machinery_amount=plant_machinery_amount,
            materials_details=data.get("materialsDetails"),
            materials_amount=materials_amount,
            total_effected_amount=total,
            attachment=attachment,
            intimation_to=data.get("intimationTo"),
            intimation_via=data.get("intimationVia"),
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(hr)
        db.session.commit()

        return res(
            "Hindrance Register created",
            {"id": hr.id, "hindranceNo": hr.hindrance_no, "uuid": hr.hindrance_uuid},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_hindrance_register_list(data):
    if not data.get("projectCode"):
        return res("projectCode required", [], 400)

    try:
        query = HindranceRegister.query.filter(
            HindranceRegister.project_code == data["projectCode"],
            HindranceRegister.status == "Active",
        )

        if data.get("workflowStatus"):
            query = query.filter(
                HindranceRegister.workflow_status == data["workflowStatus"]
            )

        if data.get("search"):
            s = f"%{data['search']}%"
            query = query.filter(
                HindranceRegister.hindrance_no.ilike(s) |
                HindranceRegister.title_of_hindrance.ilike(s)
            )

        rows = query.order_by(HindranceRegister.id.desc()).all()

        result = [
            {
                "id":                  row.id,
                "hindranceNo":         row.hindrance_no,
                "uuid":                row.hindrance_uuid,
                "hindranceDate":       _fmt_date(row.hindrance_date),
                "titleOfHindrance":    row.title_of_hindrance,
                "manpowerAmount":      float(row.manpower_amount or 0),
                "plantMachineryAmount":float(row.plant_machinery_amount or 0),
                "materialsAmount":     float(row.materials_amount or 0),
                "totalEffectedAmount": float(row.total_effected_amount or 0),
                "intimationTo":        row.intimation_to,
                "workflowStatus":      row.workflow_status,
                "createdBy":           row.creator.username if row.creator else None,
                "createdAt":           row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]

        return res("Hindrance Register list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS BY ID
# ══════════════════════════════════════════════════════════════════

def get_hindrance_register_details(hr_id):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)
        return res("Hindrance Register details fetched", _serialise(hr), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS BY UUID (public)
# ══════════════════════════════════════════════════════════════════

def get_hindrance_register_by_uuid(hr_uuid):
    try:
        hr = HindranceRegister.query.filter_by(hindrance_uuid=hr_uuid).first()
        if not hr:
            return res("Hindrance Register not found", [], 404)
        return res("Hindrance Register details fetched", _serialise(hr), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_hindrance_register(hr_id, data, user_id, files=None):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if hr.locked:
            return res("Only Draft or Reback records can be edited", [], 400)

        if not is_creator(hr.project_code, MODULE_CODE, user_id):
            return res("You are not a Hindrance Register creator", [], 403)

        simple_fields = [
            ("hindranceDate",         "hindrance_date"),
            ("titleOfHindrance",      "title_of_hindrance"),
            ("causeOfHindrance",      "cause_of_hindrance"),
            ("manpowerDetails",       "manpower_details"),
            ("plantMachineryDetails", "plant_machinery_details"),
            ("materialsDetails",      "materials_details"),
            ("intimationTo",          "intimation_to"),
            ("intimationVia",         "intimation_via"),
        ]

        for key, col in simple_fields:
            if key in data:
                setattr(hr, col, data[key] or None)

        # Recalculate amounts if any amount field is provided
        if any(k in data for k in ("manpowerAmount", "plantMachineryAmount", "materialsAmount")):
            hr.manpower_amount        = float(data.get("manpowerAmount") or hr.manpower_amount or 0)
            hr.plant_machinery_amount = float(data.get("plantMachineryAmount") or hr.plant_machinery_amount or 0)
            hr.materials_amount       = float(data.get("materialsAmount") or hr.materials_amount or 0)
            hr.total_effected_amount  = _calc_total(
                hr.manpower_amount,
                hr.plant_machinery_amount,
                hr.materials_amount
            )

        if files:
            att_file = files.get("attachment")
            if att_file:
                hr.attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="hindrance_register",
                    subFolder=hr.hindrance_no,
                    fileName="attachment"
                )

        hr.updated_by = user_id
        hr.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Hindrance Register updated", {"id": hr.id, "hindranceNo": hr.hindrance_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_hindrance_register(hr_id, submitted_by):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if hr.workflow_status not in ("Draft", "Reback"):
            return res("Hindrance Register already submitted", [], 400)

        if hr.workflow_status == "Reback":
            hr.current_level = 0

        first_level = get_first_approver(hr.project_code, MODULE_CODE)

        if not first_level:
            hr.workflow_status = "Approved"
            hr.locked = True
            hr.approved_by = submitted_by
            hr.submitted_at = datetime.utcnow()
            hr.final_approved_at = datetime.utcnow()
        else:
            hr.workflow_status = f"Pending_L{first_level.level_no}"
            hr.current_level = first_level.level_no
            hr.locked = True
            hr.submitted_at = datetime.utcnow()

        create_history(
            project_code=hr.project_code,
            module_code=MODULE_CODE,
            record_id=hr.id,
            level_no=hr.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        hr.submitted_by = submitted_by
        hr.updated_by = submitted_by
        hr.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Hindrance Register submitted successfully",
            {"id": hr.id, "hindranceNo": hr.hindrance_no, "workflowStatus": hr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_hindrance_register(hr_id, approved_by, comments=None):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if not hr.workflow_status.startswith("Pending"):
            return res("Hindrance Register not pending", [], 400)

        if not is_current_approver(hr.project_code, MODULE_CODE, hr.current_level, approved_by):
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(hr.project_code, MODULE_CODE, hr.current_level)

        if next_level:
            create_history(
                project_code=hr.project_code,
                module_code=MODULE_CODE,
                record_id=hr.id,
                level_no=hr.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            hr.current_level = next_level.level_no
            hr.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=hr.project_code,
                module_code=MODULE_CODE,
                record_id=hr.id,
                level_no=hr.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            hr.workflow_status = "Approved"
            hr.locked = True
            hr.approved_by = approved_by
            hr.final_approved_at = datetime.utcnow()

        hr.updated_by = approved_by
        hr.updated_at = datetime.utcnow()
        db.session.commit()

        return res(
            "Hindrance Register approved successfully",
            {"id": hr.id, "workflowStatus": hr.workflow_status, "currentLevel": hr.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_hindrance_register(hr_id, reback_by, comments=None):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if not hr.workflow_status.startswith("Pending"):
            return res("Hindrance Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(hr.project_code, MODULE_CODE, hr.current_level, reback_by):
            return res("You are not current approver", [], 403)

        hr.workflow_status = "Reback"
        hr.locked = False
        hr.correction_sent_at = datetime.utcnow()
        hr.updated_by = reback_by
        hr.updated_at = datetime.utcnow()

        create_history(
            project_code=hr.project_code,
            module_code=MODULE_CODE,
            record_id=hr.id,
            level_no=hr.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "Hindrance Register sent for correction",
            {"id": hr.id, "workflowStatus": hr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_hindrance_register(hr_id, rejected_by, comments=None):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if not hr.workflow_status.startswith("Pending"):
            return res("Hindrance Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(hr.project_code, MODULE_CODE, hr.current_level, rejected_by):
            return res("You are not current approver", [], 403)

        hr.workflow_status = "Rejected"
        hr.locked = True
        hr.rejected_at = datetime.utcnow()
        hr.rejected_by = rejected_by
        hr.status = "Inactive"
        hr.updated_by = rejected_by
        hr.updated_at = datetime.utcnow()

        create_history(
            project_code=hr.project_code,
            module_code=MODULE_CODE,
            record_id=hr.id,
            level_no=hr.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "Hindrance Register rejected",
            {"id": hr.id, "workflowStatus": hr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. DELETE
# ══════════════════════════════════════════════════════════════════

def delete_hindrance_register(hr_id):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        if hr.locked:
            return res("Only Draft or Reback records can be deleted", [], 400)

        db.session.delete(hr)
        db.session.commit()

        return res("Hindrance Register deleted", [], 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_hindrance_register_history(hr_id):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        rows = get_history(MODULE_CODE, hr.id)

        history = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]

        steps = get_approval_steps(hr.project_code, MODULE_CODE, hr, rows)

        return res("Hindrance Register history fetched", {
            "workflowStatus": hr.workflow_status,
            "currentLevel":   hr.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_hindrance_register_my_approval_status(hr_id, user_id):
    try:
        hr = HindranceRegister.query.get(hr_id)
        if not hr:
            return res("Hindrance Register not found", [], 404)

        data = get_my_approval_status(hr.project_code, MODULE_CODE, hr, user_id)
        return res("Approval status fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
