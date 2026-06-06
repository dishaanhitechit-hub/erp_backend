from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime

from app.models.drawingRegister import DrawingRegister
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
)


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _fmt_time(t):
    if t is None:
        return None
    return t.strftime("%H:%M")


def generate_dr_no():
    last = (
        db.session.query(DrawingRegister.dr_no)
        .order_by(DrawingRegister.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 900000
    else:
        last_serial = 900000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE DRAWING REGISTER
# ══════════════════════════════════════════════════════════════════

def create_drawing_register(data, user_id, files=None):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            "drawing_register",
            user_id
        )

        if not allowed:
            return res("You are not Drawing Register creator", [], 403)

        dr_no = generate_dr_no()

        # ── file upload ────────────────────────────────────────
        attachment = None
        if files:
            att_file = files.get("attachment")
            if att_file:
                attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="drawing_register",
                    subFolder=dr_no,
                    fileName="attachment"
                )

        dr = DrawingRegister(
            dr_no=dr_no,
            project_code=data.get("projectCode"),

            # Drawing Details
            drawing_no=data.get("drawingNo"),
            revision=data.get("revision"),
            drawing_title=data.get("drawingTitle"),

            # Location Details
            reference_order_no=data.get("referenceOrderNo"),
            project_sub_location=data.get("projectSubLocation"),
            segment_layer=data.get("segmentLayer"),

            # Received Details
            received_date=data.get("receivedDate") or None,
            received_time=data.get("receivedTime") or None,
            received_by=data.get("receivedBy"),
            delivered_by=data.get("deliveredBy"),
            delivery_mode=data.get("deliveryMode"),
            delivery_reference=data.get("deliveryReference"),

            attachment=attachment,
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(dr)
        db.session.commit()

        return res(
            "Drawing Register created",
            {"drId": dr.id, "drNo": dr.dr_no},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_drawing_register_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = DrawingRegister.query.filter(
            DrawingRegister.project_code == data.get("projectCode")
        )

        if data.get("workflowStatus"):
            query = query.filter(
                DrawingRegister.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                DrawingRegister.dr_no.ilike(f"%{data.get('search')}%") |
                DrawingRegister.drawing_no.ilike(f"%{data.get('search')}%") |
                DrawingRegister.drawing_title.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(DrawingRegister.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id": row.id,
                "drNo": row.dr_no,
                "projectCode": row.project_code,
                "drawingNo": row.drawing_no,
                "revision": row.revision,
                "drawingTitle": row.drawing_title,
                "referenceOrderNo": row.reference_order_no,
                "receivedDate": _fmt_date(row.received_date),
                "receivedBy": row.received_by,
                "workflowStatus": row.workflow_status,
            })

        return res("Drawing Register list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_drawing_register_details(dr_id):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        data = {
            "id": dr.id,
            "drNo": dr.dr_no,
            "projectCode": dr.project_code,

            # Drawing Details
            "drawingNo": dr.drawing_no,
            "revision": dr.revision,
            "drawingTitle": dr.drawing_title,

            # Location Details
            "referenceOrderNo": dr.reference_order_no,
            "projectSubLocation": dr.project_sub_location,
            "segmentLayer": dr.segment_layer,

            # Received Details
            "receivedDate": _fmt_date(dr.received_date),
            "receivedTime": _fmt_time(dr.received_time),
            "receivedBy": dr.received_by,
            "deliveredBy": dr.delivered_by,
            "deliveryMode": dr.delivery_mode,
            "deliveryReference": dr.delivery_reference,

            "attachment": dr.attachment,
            "workflowStatus": dr.workflow_status,
            "currentLevel": dr.current_level,
            "locked": dr.locked,
        }

        return res("Drawing Register details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_drawing_register(dr_id, data, user_id, files=None):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        if dr.locked:
            return res("Drawing Register cannot be edited", [], 400)

        if dr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(dr.project_code, "drawing_register", user_id)
        if not allowed:
            return res("You are not Drawing Register creator", [], 403)

        # Drawing Details
        if data.get("drawingNo") is not None:
            dr.drawing_no = data.get("drawingNo")
        if data.get("revision") is not None:
            dr.revision = data.get("revision")
        if data.get("drawingTitle") is not None:
            dr.drawing_title = data.get("drawingTitle")

        # Location Details
        if data.get("referenceOrderNo") is not None:
            dr.reference_order_no = data.get("referenceOrderNo")
        if data.get("projectSubLocation") is not None:
            dr.project_sub_location = data.get("projectSubLocation")
        if data.get("segmentLayer") is not None:
            dr.segment_layer = data.get("segmentLayer")

        # Received Details
        if data.get("receivedDate") is not None:
            dr.received_date = data.get("receivedDate") or None
        if data.get("receivedTime") is not None:
            dr.received_time = data.get("receivedTime") or None
        if data.get("receivedBy") is not None:
            dr.received_by = data.get("receivedBy")
        if data.get("deliveredBy") is not None:
            dr.delivered_by = data.get("deliveredBy")
        if data.get("deliveryMode") is not None:
            dr.delivery_mode = data.get("deliveryMode")
        if data.get("deliveryReference") is not None:
            dr.delivery_reference = data.get("deliveryReference")

        # File
        if files:
            att_file = files.get("attachment")
            if att_file:
                dr.attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="drawing_register",
                    subFolder=dr.dr_no,
                    fileName="attachment"
                )

        if dr.workflow_status == "Reback":
            dr.correction_sent_at = None

        dr.updated_by = user_id
        dr.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Drawing Register updated successfully",
            {"drId": dr.id, "drNo": dr.dr_no},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_drawing_register(dr_id, submitted_by=None):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        if dr.workflow_status not in ["Draft", "Reback"]:
            return res("Drawing Register already submitted", [], 400)

        if dr.workflow_status == "Reback":
            dr.current_level = 0

        first_level = get_first_approver(dr.project_code, "drawing_register")

        if not first_level:
            dr.workflow_status = "Approved"
            dr.locked = True
            dr.approved_by = submitted_by
            dr.submitted_at = datetime.utcnow()
            dr.final_approved_at = datetime.utcnow()
        else:
            dr.workflow_status = f"Pending_L{first_level.level_no}"
            dr.current_level = first_level.level_no
            dr.locked = True
            dr.submitted_at = datetime.utcnow()

        create_history(
            project_code=dr.project_code,
            module_code="drawing_register",
            record_id=dr.id,
            level_no=dr.current_level,
            action="SUBMIT",
            action_by=submitted_by
        )

        dr.submitted_by = submitted_by
        dr.updated_by = submitted_by
        dr.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Drawing Register submitted successfully",
            {
                "drId": dr.id,
                "drNo": dr.dr_no,
                "workflowStatus": dr.workflow_status
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
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_drawing_register(dr_id, approved_by=None, comments=None):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        if not dr.workflow_status.startswith("Pending"):
            return res("Drawing Register not pending", [], 400)

        allowed = is_current_approver(
            dr.project_code,
            "drawing_register",
            dr.current_level,
            approved_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            dr.project_code,
            "drawing_register",
            dr.current_level
        )

        if next_level:
            create_history(
                project_code=dr.project_code,
                module_code="drawing_register",
                record_id=dr.id,
                level_no=dr.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments
            )
            dr.current_level = next_level.level_no
            dr.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=dr.project_code,
                module_code="drawing_register",
                record_id=dr.id,
                level_no=dr.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments
            )
            dr.workflow_status = "Approved"
            dr.locked = True
            dr.approved_by = approved_by
            dr.final_approved_at = datetime.utcnow()

        dr.updated_by = approved_by
        dr.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Drawing Register approved successfully",
            {
                "drId": dr.id,
                "workflowStatus": dr.workflow_status,
                "currentLevel": dr.current_level
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
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_drawing_register(dr_id, reback_by=None, comments=None):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        if not dr.workflow_status.startswith("Pending"):
            return res("Drawing Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            dr.project_code,
            "drawing_register",
            dr.current_level,
            reback_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        dr.workflow_status = "Reback"
        dr.locked = False
        dr.correction_sent_at = datetime.utcnow()
        dr.updated_by = reback_by
        dr.updated_at = datetime.utcnow()

        create_history(
            project_code=dr.project_code,
            module_code="drawing_register",
            record_id=dr.id,
            level_no=dr.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "Drawing Register sent for correction",
            {"drId": dr.id, "workflowStatus": dr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_drawing_register(dr_id, rejected_by=None, comments=None):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        if not dr.workflow_status.startswith("Pending"):
            return res("Drawing Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            dr.project_code,
            "drawing_register",
            dr.current_level,
            rejected_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        dr.workflow_status = "Rejected"
        dr.locked = True
        dr.rejected_at = datetime.utcnow()
        dr.rejected_by = rejected_by
        dr.status = "Inactive"
        dr.updated_by = rejected_by
        dr.updated_at = datetime.utcnow()

        create_history(
            project_code=dr.project_code,
            module_code="drawing_register",
            record_id=dr.id,
            level_no=dr.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "Drawing Register rejected",
            {"drId": dr.id, "workflowStatus": dr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_drawing_register_history(dr_id):
    try:

        dr = DrawingRegister.query.get(dr_id)

        if not dr:
            return res("Drawing Register not found", [], 404)

        rows = get_history("drawing_register", dr.id)

        data = []
        for row in rows:
            data.append({
                "id": row.id,
                "action": row.action,
                "level": row.level_no,
                "comments": row.comments,
                "actionBy": row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y%m%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("Drawing Register history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
