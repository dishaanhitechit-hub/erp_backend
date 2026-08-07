import uuid as _uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.bbsRegister import BbsRegister
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    get_gap_level,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

MODULE_CODE = "bbs_register"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


def _fmt_time(t):
    if t is None:
        return None
    return t.strftime("%H:%M")


def _generate_bbs_no():
    db.session.execute(text("SELECT pg_advisory_xact_lock(470000)"))
    last = (
        db.session.query(BbsRegister.bbs_no)
        .order_by(BbsRegister.id.desc())
        .first()
    )
    if not last:
        return "BBS001"
    suffix = last[0][3:]   # strip "BBS"
    next_num = int(suffix) + 1
    return "BBS" + str(next_num).zfill(len(suffix))


def _serialise(bbs):
    return {
        "id":                  bbs.id,
        "bbsNo":               bbs.bbs_no,
        "uuid":                bbs.bbs_uuid,
        "projectCode":         bbs.project_code,
        "projectName":         bbs.project.project_name if bbs.project else None,
        "revision":            bbs.revision,
        "bbsTitle":            bbs.bbs_title,
        "referenceOrderNo":    bbs.reference_order_no,
        "projectSubLocation":  bbs.project_sub_location,
        "segmentLayer":        bbs.segment_layer,
        "receivedDate":        _fmt_date(bbs.received_date),
        "receivedTime":        _fmt_time(bbs.received_time),
        "receivedBy":          bbs.received_by,
        "deliveredBy":         bbs.delivered_by,
        "deliveryMode":        bbs.delivery_mode,
        "deliveryReference":   bbs.delivery_reference,
        "attachment":          bbs.attachment,
        "workflowStatus":      bbs.workflow_status,
        "status":              bbs.status,
        "currentLevel":        bbs.current_level,
        "locked":              bbs.locked,
        "createdBy":           bbs.creator.username if bbs.creator else None,
        "createdAt":           bbs.created_at.strftime("%Y-%m-%d %H:%M:%S") if bbs.created_at else None,
        "approvedBy":          bbs.approver.username if bbs.approver else None,
        "finalApprovedAt":     bbs.final_approved_at.strftime("%Y-%m-%d %H:%M:%S") if bbs.final_approved_at else None,
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_bbs_register(data, user_id, files=None):
    project_code = data.get("projectCode")

    if not project_code:
        return res("projectCode required", [], 400)

    if not is_creator(project_code, MODULE_CODE, user_id):
        return res("You are not a BBS Register creator", [], 403)

    try:
        new_uuid = str(_uuid.uuid4())
        bbs_no = _generate_bbs_no()

        attachment = None
        if files:
            att_file = files.get("attachment")
            if att_file:
                attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="bbs_register",
                    subFolder=bbs_no,
                    fileName="attachment"
                )

        bbs = BbsRegister(
            bbs_no=bbs_no,
            bbs_uuid=new_uuid,
            project_code=project_code,
            revision=data.get("revision"),
            bbs_title=data.get("bbsTitle"),
            reference_order_no=data.get("referenceOrderNo"),
            project_sub_location=data.get("projectSubLocation"),
            segment_layer=data.get("segmentLayer"),
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

        db.session.add(bbs)
        db.session.commit()

        return res(
            "BBS Register created",
            {"id": bbs.id, "bbsNo": bbs.bbs_no, "uuid": bbs.bbs_uuid},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_bbs_register_list(data):
    if not data.get("projectCode"):
        return res("projectCode required", [], 400)

    try:
        query = BbsRegister.query.filter(
            BbsRegister.project_code == data["projectCode"],
            BbsRegister.status == "Active",
        )

        if data.get("workflowStatus"):
            query = query.filter(
                BbsRegister.workflow_status == data["workflowStatus"]
            )

        if data.get("search"):
            s = f"%{data['search']}%"
            query = query.filter(
                BbsRegister.bbs_no.ilike(s) |
                BbsRegister.bbs_title.ilike(s)
            )

        rows = query.order_by(BbsRegister.id.desc()).all()

        result = [
            {
                "id":               row.id,
                "bbsNo":            row.bbs_no,
                "uuid":             row.bbs_uuid,
                "projectCode":      row.project_code,
                "revision":         row.revision,
                "bbsTitle":         row.bbs_title,
                "referenceOrderNo": row.reference_order_no,
                "receivedDate":     _fmt_date(row.received_date),
                "receivedBy":       row.received_by,
                "workflowStatus":   row.workflow_status,
                "createdBy":        row.creator.username if row.creator else None,
                "createdAt":        row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]

        return res("BBS Register list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS BY ID
# ══════════════════════════════════════════════════════════════════

def get_bbs_register_details(bbs_id):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)
        return res("BBS Register details fetched", _serialise(bbs), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS BY UUID (public)
# ══════════════════════════════════════════════════════════════════

def get_bbs_register_by_uuid(bbs_uuid):
    try:
        bbs = BbsRegister.query.filter_by(bbs_uuid=bbs_uuid).first()
        if not bbs:
            return res("BBS Register not found", [], 404)
        return res("BBS Register details fetched", _serialise(bbs), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_bbs_register(bbs_id, data, user_id, files=None):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if bbs.locked:
            return res("Only Draft or Reback records can be edited", [], 400)

        if not is_creator(bbs.project_code, MODULE_CODE, user_id):
            return res("You are not a BBS Register creator", [], 403)

        fields = [
            ("revision",          "revision"),
            ("bbsTitle",          "bbs_title"),
            ("referenceOrderNo",  "reference_order_no"),
            ("projectSubLocation","project_sub_location"),
            ("segmentLayer",      "segment_layer"),
            ("receivedBy",        "received_by"),
            ("deliveredBy",       "delivered_by"),
            ("deliveryMode",      "delivery_mode"),
            ("deliveryReference", "delivery_reference"),
        ]

        for key, col in fields:
            if key in data:
                setattr(bbs, col, data[key] or None)

        if "receivedDate" in data:
            bbs.received_date = data["receivedDate"] or None
        if "receivedTime" in data:
            bbs.received_time = data["receivedTime"] or None

        if files:
            att_file = files.get("attachment")
            if att_file:
                bbs.attachment = upload_file_to_bunny(
                    file=att_file,
                    mainFolder="bbs_register",
                    subFolder=bbs.bbs_no,
                    fileName="attachment"
                )

        bbs.updated_by = user_id
        bbs.updated_at = datetime.utcnow()

        db.session.commit()

        return res("BBS Register updated", {"id": bbs.id, "bbsNo": bbs.bbs_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_bbs_register(bbs_id, submitted_by):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if bbs.workflow_status not in ("Draft", "Reback"):
            return res("BBS Register already submitted", [], 400)

        if bbs.workflow_status == "Reback":
            bbs.current_level = 0

        first_level = get_first_approver(bbs.project_code, MODULE_CODE)

        if not first_level:
            bbs.workflow_status = "Approved"
            bbs.locked = True
            bbs.approved_by = submitted_by
            bbs.submitted_at = datetime.utcnow()
            bbs.final_approved_at = datetime.utcnow()
        else:
            bbs.workflow_status = f"Pending_L{first_level.level_no}"
            bbs.current_level = first_level.level_no
            bbs.locked = True
            bbs.submitted_at = datetime.utcnow()

        create_history(
            project_code=bbs.project_code,
            module_code=MODULE_CODE,
            record_id=bbs.id,
            level_no=bbs.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        bbs.submitted_by = submitted_by
        bbs.updated_by = submitted_by
        bbs.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BBS Register submitted successfully",
            {"id": bbs.id, "bbsNo": bbs.bbs_no, "workflowStatus": bbs.workflow_status},
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

def approve_bbs_register(bbs_id, approved_by, comments=None):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if not bbs.workflow_status.startswith("Pending"):
            return res("BBS Register not pending", [], 400)

        if not is_current_approver(bbs.project_code, MODULE_CODE, bbs.current_level, approved_by):
            return res("You are not current approver", [], 403)

        gap = get_gap_level(bbs.project_code, MODULE_CODE, bbs.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(bbs.project_code, MODULE_CODE, bbs.current_level)

        if next_level:
            create_history(
                project_code=bbs.project_code,
                module_code=MODULE_CODE,
                record_id=bbs.id,
                level_no=bbs.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            bbs.current_level = next_level.level_no
            bbs.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=bbs.project_code,
                module_code=MODULE_CODE,
                record_id=bbs.id,
                level_no=bbs.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            bbs.workflow_status = "Approved"
            bbs.locked = True
            bbs.approved_by = approved_by
            bbs.final_approved_at = datetime.utcnow()

        bbs.updated_by = approved_by
        bbs.updated_at = datetime.utcnow()
        db.session.commit()

        return res(
            "BBS Register approved successfully",
            {"id": bbs.id, "workflowStatus": bbs.workflow_status, "currentLevel": bbs.current_level},
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

def reback_bbs_register(bbs_id, reback_by, comments=None):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if not bbs.workflow_status.startswith("Pending"):
            return res("BBS Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(bbs.project_code, MODULE_CODE, bbs.current_level, reback_by):
            return res("You are not current approver", [], 403)

        bbs.workflow_status = "Reback"
        bbs.locked = False
        bbs.correction_sent_at = datetime.utcnow()
        bbs.updated_by = reback_by
        bbs.updated_at = datetime.utcnow()

        create_history(
            project_code=bbs.project_code,
            module_code=MODULE_CODE,
            record_id=bbs.id,
            level_no=bbs.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "BBS Register sent for correction",
            {"id": bbs.id, "workflowStatus": bbs.workflow_status},
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

def reject_bbs_register(bbs_id, rejected_by, comments=None):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if not bbs.workflow_status.startswith("Pending"):
            return res("BBS Register not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(bbs.project_code, MODULE_CODE, bbs.current_level, rejected_by):
            return res("You are not current approver", [], 403)

        bbs.workflow_status = "Rejected"
        bbs.locked = True
        bbs.rejected_at = datetime.utcnow()
        bbs.rejected_by = rejected_by
        bbs.status = "Inactive"
        bbs.updated_by = rejected_by
        bbs.updated_at = datetime.utcnow()

        create_history(
            project_code=bbs.project_code,
            module_code=MODULE_CODE,
            record_id=bbs.id,
            level_no=bbs.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "BBS Register rejected",
            {"id": bbs.id, "workflowStatus": bbs.workflow_status},
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

def delete_bbs_register(bbs_id):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        if bbs.locked:
            return res("Only Draft or Reback records can be deleted", [], 400)

        db.session.delete(bbs)
        db.session.commit()

        return res("BBS Register deleted", [], 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_bbs_register_history(bbs_id):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        rows = get_history(MODULE_CODE, bbs.id)

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

        steps = get_approval_steps(bbs.project_code, MODULE_CODE, bbs, rows)

        return res("BBS Register history fetched", {
            "workflowStatus": bbs.workflow_status,
            "currentLevel":   bbs.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_bbs_register_my_approval_status(bbs_id, user_id):
    try:
        bbs = BbsRegister.query.get(bbs_id)
        if not bbs:
            return res("BBS Register not found", [], 404)

        data = get_my_approval_status(bbs.project_code, MODULE_CODE, bbs, user_id)
        return res("Approval status fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
