from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime

from app.models.brrMaster import BrrMaster
from app.models.orderMaster import OrderMaster
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

_MODULE = "bill_receive_register"


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def generate_brr_no():
    last = (
        db.session.query(BrrMaster.brr_no)
        .order_by(BrrMaster.id.desc())
        .with_for_update()
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
# 1. GET ORDERS BY VENDOR (filter panel)
# ══════════════════════════════════════════════════════════════════

def get_orders_by_vendor(data):
    try:
        vendor_id    = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        query = OrderMaster.query.filter(
            OrderMaster.vendor_id    == vendor_id,
            OrderMaster.project_code == project_code,
            OrderMaster.workflow_status == "Approved"
        )

        if data.get("orderCategory"):
            query = query.filter(OrderMaster.category_code == data.get("orderCategory"))

        rows = query.order_by(OrderMaster.id.desc()).all()

        result = [
            {
                "id":           row.id,
                "orderNo":      row.order_no,
                "orderDate":    _fmt_date(row.order_date),
                "categoryCode": row.category_code,
                "basicAmount":  float(row.basic_amount or 0),
                "totalAmount":  float(row.total_amount or 0),
            }
            for row in rows
        ]

        return res("Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE BRR
# ══════════════════════════════════════════════════════════════════

def create_brr(data, user_id, files=None):
    try:
        allowed = is_creator(data.get("projectCode"), _MODULE, user_id)
        if not allowed:
            return res("You are not BRR creator", [], 403)

        brr_no = generate_brr_no()

        basic  = float(data.get("basicAmount") or 0)
        gst    = float(data.get("gstAmount")   or 0)
        total  = basic + gst

        # ── file upload ────────────────────────────────────────
        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file       = doc_file,
                    mainFolder = "brr",
                    subFolder  = brr_no,
                    fileName   = "attached_doc"
                )

        brr = BrrMaster(
            brr_no             = brr_no,
            brr_date           = datetime.utcnow().date(),
            project_code       = data.get("projectCode"),
            vendor_id          = data.get("vendorId"),
            order_category     = data.get("orderCategory"),
            order_id           = data.get("orderId") or None,
            party_bill_no      = data.get("partyBillNo"),
            party_date         = data.get("partyDate") or None,
            received_category  = data.get("receivedCategory"),
            submitted_by_name  = data.get("submittedByName"),
            submission_date    = data.get("submissionDate") or None,
            received_through   = data.get("receivedThrough"),
            received_reference = data.get("receivedReference"),
            basic_amount       = basic,
            gst_amount         = gst,
            total_amount       = total,
            attached_doc       = attached_doc,
            workflow_status    = "Draft",
            current_level      = 0,
            locked             = False,
            created_by         = user_id,
        )

        db.session.add(brr)
        db.session.commit()

        return res(
            "BRR created",
            {"brrId": brr.id, "brrNo": brr.brr_no, "attachedDoc": brr.attached_doc},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. BRR LIST
# ══════════════════════════════════════════════════════════════════

def get_brr_list(data):
    try:
        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BrrMaster.query.filter(
            BrrMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(BrrMaster.vendor_id == data.get("vendorId"))

        if data.get("workflowStatus"):
            query = query.filter(BrrMaster.workflow_status == data.get("workflowStatus"))

        if data.get("search"):
            query = query.filter(BrrMaster.brr_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(BrrMaster.id.desc()).all()

        result = [
            {
                "id":              row.id,
                "brrNo":           row.brr_no,
                "brrDate":         _fmt_date(row.brr_date),
                "projectCode":     row.project_code,
                "partyName":       row.vendor.ledger_name if row.vendor else None,
                "orderCategory":   row.order_category,
                "orderNo":         row.order.order_no    if row.order  else None,
                "partyBillNo":     row.party_bill_no,
                "basicAmount":     float(row.basic_amount or 0),
                "totalAmount":     float(row.total_amount or 0),
                "workflowStatus":  row.workflow_status,
                "orderDate": _fmt_date(row.order.order_date) if row.order else None,
                "partyDate": _fmt_date(row.party_date),
                "bookedAmount":row.booked_amount
            }
            for row in rows
        ]

        return res("BRR list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. BRR DETAILS
# ══════════════════════════════════════════════════════════════════

def get_brr_details(brr_id):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        data = {
            "id":                brr.id,
            "brrNo":             brr.brr_no,
            "brrDate":           _fmt_date(brr.brr_date),
            "projectCode":       brr.project_code,
            "vendorId":          brr.vendor_id,
            "partyName":         brr.vendor.ledger_name        if brr.vendor else None,
            "partyAddress":      brr.vendor.registered_address if brr.vendor else None,
            "partyGstn":         brr.vendor.gstin              if brr.vendor else None,
            "orderCategory":     brr.order_category,
            "orderId":           brr.order_id,
            "orderNo":           brr.order.order_no            if brr.order  else None,
            "orderDate":         _fmt_date(brr.order.order_date) if brr.order else None,
            "partyBillNo":       brr.party_bill_no,
            "partyDate":         _fmt_date(brr.party_date),
            "receivedCategory":  brr.received_category,
            "submittedByName":       brr.submitted_by_name,
            "submissionDate":    _fmt_date(brr.submission_date),
            "receivedThrough":   brr.received_through,
            "receivedReference": brr.received_reference,
            "basicAmount":       float(brr.basic_amount or 0),
            "gstAmount":         float(brr.gst_amount   or 0),
            "totalAmount":       float(brr.total_amount  or 0),
            "attachedDoc":       brr.attached_doc,
            "workflowStatus":    brr.workflow_status,
            "currentLevel":      brr.current_level,
            "locked":            brr.locked,
        }

        return res("BRR details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT BRR
# ══════════════════════════════════════════════════════════════════

def edit_brr(brr_id, data, user_id, files=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if brr.locked:
            return res("BRR cannot be edited", [], 400)

        if brr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback BRR can be edited", [], 400)

        allowed = is_creator(brr.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not BRR creator", [], 403)

        fields = [
            ("vendorId",          "vendor_id"),
            ("orderCategory",     "order_category"),
            ("orderId",           "order_id"),
            ("partyBillNo",       "party_bill_no"),
            ("partyDate",         "party_date"),
            ("receivedCategory",  "received_category"),
            ("submittedByName",       "submitted_by_name"),
            ("submissionDate",    "submission_date"),
            ("receivedThrough",   "received_through"),
            ("receivedReference", "received_reference"),
        ]
        for key, attr in fields:
            if data.get(key) is not None:
                setattr(brr, attr, data.get(key) or None)

        if data.get("basicAmount") is not None or data.get("gstAmount") is not None:
            basic = float(data.get("basicAmount") or brr.basic_amount or 0)
            gst   = float(data.get("gstAmount")   or brr.gst_amount   or 0)
            brr.basic_amount = basic
            brr.gst_amount   = gst
            brr.total_amount = basic + gst

        # ── file update ────────────────────────────────────────
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                brr.attached_doc = upload_file_to_bunny(
                    file       = doc_file,
                    mainFolder = "brr",
                    subFolder  = brr.brr_no,
                    fileName   = "attached_doc"
                )

        if brr.workflow_status == "Reback":
            brr.correction_sent_at = None

        brr.updated_by = user_id
        brr.updated_at = datetime.utcnow()

        db.session.commit()

        return res("BRR updated", {"brrId": brr.id, "brrNo": brr.brr_no, "attachedDoc": brr.attached_doc}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT BRR
# ══════════════════════════════════════════════════════════════════

def submit_brr(brr_id, submitted_by=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if brr.workflow_status not in ["Draft", "Reback"]:
            return res("BRR already submitted", [], 400)

        if brr.workflow_status == "Reback":
            brr.current_level = 0

        first_level = get_first_approver(brr.project_code, _MODULE)

        if not first_level:
            brr.workflow_status   = "Approved"
            brr.locked            = True
            brr.approved_by       = submitted_by
            brr.submitted_at      = datetime.utcnow()
            brr.final_approved_at = datetime.utcnow()
        else:
            brr.workflow_status = f"Pending_L{first_level.level_no}"
            brr.current_level   = first_level.level_no
            brr.locked          = True
            brr.submitted_at    = datetime.utcnow()

        create_history(
            project_code = brr.project_code,
            module_code  = _MODULE,
            record_id    = brr.id,
            level_no     = brr.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        brr.submitted_by = submitted_by
        brr.updated_by   = submitted_by
        brr.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "BRR submitted",
            {"brrId": brr.id, "brrNo": brr.brr_no, "workflowStatus": brr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE BRR
# ══════════════════════════════════════════════════════════════════

def approve_brr(brr_id, approved_by=None, comments=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if not brr.workflow_status.startswith("Pending"):
            return res("BRR not pending", [], 400)

        allowed = is_current_approver(brr.project_code, _MODULE, brr.current_level, approved_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(brr.project_code, _MODULE, brr.current_level)

        if next_level:
            create_history(
                project_code = brr.project_code,
                module_code  = _MODULE,
                record_id    = brr.id,
                level_no     = brr.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brr.current_level   = next_level.level_no
            brr.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = brr.project_code,
                module_code  = _MODULE,
                record_id    = brr.id,
                level_no     = brr.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brr.workflow_status   = "Approved"
            brr.locked            = True
            brr.approved_by       = approved_by
            brr.final_approved_at = datetime.utcnow()

        brr.updated_by = approved_by
        brr.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BRR approved",
            {"brrId": brr.id, "workflowStatus": brr.workflow_status, "currentLevel": brr.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK BRR
# ══════════════════════════════════════════════════════════════════

def reback_brr(brr_id, reback_by=None, comments=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if not brr.workflow_status.startswith("Pending"):
            return res("BRR not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(brr.project_code, _MODULE, brr.current_level, reback_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        brr.workflow_status    = "Reback"
        brr.locked             = False
        brr.correction_sent_at = datetime.utcnow()
        brr.updated_by         = reback_by
        brr.updated_at         = datetime.utcnow()

        create_history(
            project_code = brr.project_code,
            module_code  = _MODULE,
            record_id    = brr.id,
            level_no     = brr.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRR sent for correction",
            {"brrId": brr.id, "workflowStatus": brr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT BRR
# ══════════════════════════════════════════════════════════════════

def reject_brr(brr_id, rejected_by=None, comments=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if not brr.workflow_status.startswith("Pending"):
            return res("BRR not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(brr.project_code, _MODULE, brr.current_level, rejected_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        brr.workflow_status = "Rejected"
        brr.locked          = True
        brr.rejected_at     = datetime.utcnow()
        brr.rejected_by     = rejected_by
        brr.status          = "Inactive"
        brr.updated_by      = rejected_by
        brr.updated_at      = datetime.utcnow()

        create_history(
            project_code = brr.project_code,
            module_code  = _MODULE,
            record_id    = brr.id,
            level_no     = brr.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRR rejected",
            {"brrId": brr.id, "workflowStatus": brr.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. BRR HISTORY
# ══════════════════════════════════════════════════════════════════

def get_brr_history(brr_id):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        rows = get_history(_MODULE, brr.id)

        data = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at else None
                ),
            }
            for row in rows
        ]

        return res("BRR history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
