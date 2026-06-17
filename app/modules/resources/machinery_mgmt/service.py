from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime

from app.models.machineryLogBook import MachineryLogBook, LogBookEntry
from app.models.ORDER_projectwork import ProjectWorkOrderMaster
from app.response import res
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
)

_MODULE = "log_sheet"


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


def generate_log_book_no():
    last = (
        db.session.query(MachineryLogBook.log_book_no)
        .order_by(MachineryLogBook.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 870000
    else:
        last_serial = 870000
    return str(last_serial + 1)


def generate_log_uid():
    last = (
        db.session.query(LogBookEntry.log_uid)
        .order_by(LogBookEntry.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 860000
    else:
        last_serial = 860000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_log_book(data, user_id):
    try:

        allowed = is_creator(data.get("projectCode"), _MODULE, user_id)
        if not allowed:
            return res("You are not Log Book creator", [], 403)

        log_book = MachineryLogBook(
            log_book_no               = generate_log_book_no(),
            create_date               = data.get("createDate"),
            project_code              = data.get("projectCode"),
            party_order_id            = data.get("partyOrderId") or None,
            machinery_name            = data.get("machineryName"),
            machinery_reg_no          = data.get("machineryRegNo"),
            fuel_consumption_unit     = data.get("fuelConsumptionUnit"),
            fuel_consumption_per_unit = data.get("fuelConsumptionPerUnit") or None,
            workflow_status           = "Draft",
            current_level             = 0,
            locked                    = False,
            created_by                = user_id,
        )

        db.session.add(log_book)
        db.session.commit()

        return res(
            "Log Book created",
            {"logBookId": log_book.id, "logBookNo": log_book.log_book_no},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_log_book_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = MachineryLogBook.query.filter(
            MachineryLogBook.project_code == data.get("projectCode")
        )

        if data.get("workflowStatus"):
            query = query.filter(
                MachineryLogBook.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                MachineryLogBook.log_book_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(MachineryLogBook.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":               row.id,
                "logBookNo":        row.log_book_no,
                "createDate":       _fmt_date(row.create_date),
                "projectCode":      row.project_code,
                "partyOrderId":     row.party_order_id,
                "partyOrderNo":     row.party_order.order_no if row.party_order else None,
                "partyName":        row.party_order.vendor.ledger_name if row.party_order and row.party_order.vendor else None,
                "machineryName":    row.machinery_name,
                "machineryRegNo":   row.machinery_reg_no,
                "workflowStatus":   row.workflow_status,
            })

        return res("Log Book list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_log_book_details(log_book_id):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        data = {
            "id":                     lb.id,
            "logBookNo":              lb.log_book_no,
            "createDate":             _fmt_date(lb.create_date),
            "projectCode":            lb.project_code,
            "partyOrderId":           lb.party_order_id,
            "partyOrderNo":           lb.party_order.order_no              if lb.party_order else None,
            "partyName":              lb.party_order.vendor.ledger_name    if lb.party_order and lb.party_order.vendor else None,
            "partyAddress":           lb.party_order.vendor.registered_address if lb.party_order and lb.party_order.vendor else None,
            "machineryName":          lb.machinery_name,
            "machineryRegNo":         lb.machinery_reg_no,
            "fuelConsumptionUnit":    lb.fuel_consumption_unit,
            "fuelConsumptionPerUnit": float(lb.fuel_consumption_per_unit or 0),
            "workflowStatus":         lb.workflow_status,
            "currentLevel":           lb.current_level,
            "locked":                 lb.locked,
        }

        return res("Log Book details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_log_book(log_book_id, data, user_id):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        if lb.locked:
            return res("Log Book cannot be edited", [], 400)

        if lb.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback Log Book can be edited", [], 400)

        allowed = is_creator(lb.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not Log Book creator", [], 403)

        if data.get("createDate"):
            lb.create_date = data.get("createDate")
        if data.get("partyOrderId"):
            lb.party_order_id = data.get("partyOrderId")
        if data.get("machineryName"):
            lb.machinery_name = data.get("machineryName")
        if data.get("machineryRegNo"):
            lb.machinery_reg_no = data.get("machineryRegNo")
        if data.get("fuelConsumptionUnit"):
            lb.fuel_consumption_unit = data.get("fuelConsumptionUnit")
        if data.get("fuelConsumptionPerUnit") is not None:
            lb.fuel_consumption_per_unit = data.get("fuelConsumptionPerUnit")

        if lb.workflow_status == "Reback":
            lb.correction_sent_at = None

        lb.updated_by = user_id
        lb.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Book updated successfully",
            {"logBookId": lb.id, "logBookNo": lb.log_book_no},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_log_book(log_book_id, submitted_by=None):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        if lb.workflow_status not in ["Draft", "Reback"]:
            return res("Log Book already submitted", [], 400)

        if lb.workflow_status == "Reback":
            lb.current_level = 0

        first_level = get_first_approver(lb.project_code, _MODULE)

        if not first_level:
            lb.workflow_status   = "Approved"
            lb.locked            = True
            lb.approved_by       = submitted_by
            lb.submitted_at      = datetime.utcnow()
            lb.final_approved_at = datetime.utcnow()
        else:
            lb.workflow_status = f"Pending_L{first_level.level_no}"
            lb.current_level   = first_level.level_no
            lb.locked          = True
            lb.submitted_at    = datetime.utcnow()

        create_history(
            project_code = lb.project_code,
            module_code  = _MODULE,
            record_id    = lb.id,
            level_no     = lb.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        lb.submitted_by = submitted_by
        lb.updated_by   = submitted_by
        lb.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Book submitted successfully",
            {"logBookId": lb.id, "logBookNo": lb.log_book_no, "workflowStatus": lb.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_log_book(log_book_id, approved_by=None, comments=None):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        if not lb.workflow_status.startswith("Pending"):
            return res("Log Book not pending", [], 400)

        allowed = is_current_approver(lb.project_code, _MODULE, lb.current_level, approved_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(lb.project_code, _MODULE, lb.current_level)

        if next_level:
            create_history(
                project_code = lb.project_code,
                module_code  = _MODULE,
                record_id    = lb.id,
                level_no     = lb.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            lb.current_level   = next_level.level_no
            lb.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = lb.project_code,
                module_code  = _MODULE,
                record_id    = lb.id,
                level_no     = lb.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            lb.workflow_status   = "Approved"
            lb.locked            = True
            lb.approved_by       = approved_by
            lb.final_approved_at = datetime.utcnow()

        lb.updated_by = approved_by
        lb.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Book approved successfully",
            {"logBookId": lb.id, "workflowStatus": lb.workflow_status, "currentLevel": lb.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_log_book(log_book_id, reback_by=None, comments=None):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        if not lb.workflow_status.startswith("Pending"):
            return res("Log Book not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(lb.project_code, _MODULE, lb.current_level, reback_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        lb.workflow_status    = "Reback"
        lb.locked             = False
        lb.correction_sent_at = datetime.utcnow()
        lb.updated_by         = reback_by
        lb.updated_at         = datetime.utcnow()

        create_history(
            project_code = lb.project_code,
            module_code  = _MODULE,
            record_id    = lb.id,
            level_no     = lb.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "Log Book sent for correction",
            {"logBookId": lb.id, "workflowStatus": lb.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_log_book(log_book_id, rejected_by=None, comments=None):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        if not lb.workflow_status.startswith("Pending"):
            return res("Log Book not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(lb.project_code, _MODULE, lb.current_level, rejected_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        lb.workflow_status = "Rejected"
        lb.locked          = True
        lb.status          = "Inactive"
        lb.rejected_at     = datetime.utcnow()
        lb.rejected_by     = rejected_by
        lb.updated_by      = rejected_by
        lb.updated_at      = datetime.utcnow()

        create_history(
            project_code = lb.project_code,
            module_code  = _MODULE,
            record_id    = lb.id,
            level_no     = lb.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "Log Book rejected",
            {"logBookId": lb.id, "workflowStatus": lb.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_log_book_history(log_book_id):
    try:

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        rows = get_history(_MODULE, lb.id)

        data = []
        for row in rows:
            data.append({
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            })

        return res("Log Book history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK — 10. GET PW ORDERS (for party order dropdown)
# ══════════════════════════════════════════════════════════════════

def get_pw_orders_for_log_book(data):
    try:

        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        from app.models.ORDER_projectwork import ProjectWorkOrderMaster
        rows = ProjectWorkOrderMaster.query.filter(
            ProjectWorkOrderMaster.project_code    == project_code,
            ProjectWorkOrderMaster.workflow_status == "Approved"
        ).order_by(ProjectWorkOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":        row.id,
                "orderNo":   row.order_no,
                "orderDate": _fmt_date(row.order_date),
                "partyName": row.vendor.ledger_name if row.vendor else None,
            })

        return res("PW Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_log_entry(data, user_id):
    try:

        allowed = is_creator(data.get("projectCode"), _MODULE, user_id)
        if not allowed:
            return res("You are not Log Entry creator", [], 403)

        log_book_id = data.get("logBookId")
        if not log_book_id:
            return res("logBookId required", [], 400)

        lb = MachineryLogBook.query.get(log_book_id)
        if not lb:
            return res("Log Book not found", [], 404)

        entry = LogBookEntry(
            log_uid              = generate_log_uid(),
            log_book_id          = log_book_id,
            project_code         = data.get("projectCode"),
            running_date         = data.get("runningDate") or None,
            running_start_time   = data.get("runningStartTime") or None,
            running_finish_time  = data.get("runningFinishTime") or None,
            project_sub_location = data.get("projectSubLocation"),
            segment_layer        = data.get("segmentLayer"),
            work_monitoring_by   = data.get("workMonitoringBy"),
            operator_name        = data.get("operatorName"),
            workflow_status      = "Draft",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )

        db.session.add(entry)
        db.session.commit()

        return res(
            "Log Entry created",
            {"entryId": entry.id, "logUid": entry.log_uid},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_log_entry_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = LogBookEntry.query.filter(
            LogBookEntry.project_code == data.get("projectCode")
        )

        if data.get("logBookId"):
            query = query.filter(LogBookEntry.log_book_id == data.get("logBookId"))

        if data.get("workflowStatus"):
            query = query.filter(LogBookEntry.workflow_status == data.get("workflowStatus"))

        if data.get("search"):
            query = query.filter(LogBookEntry.log_uid.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(LogBookEntry.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":               row.id,
                "logUid":           row.log_uid,
                "logBookId":        row.log_book_id,
                "logBookNo":        row.log_book.log_book_no if row.log_book else None,
                "machineryName":    row.log_book.machinery_name if row.log_book else None,
                "machineryRegNo":   row.log_book.machinery_reg_no if row.log_book else None,
                "partyName":        row.log_book.party_order.vendor.ledger_name if row.log_book and row.log_book.party_order and row.log_book.party_order.vendor else None,
                "runningDate":      _fmt_date(row.running_date),
                "runningStartTime": _fmt_time(row.running_start_time),
                "runningFinishTime":_fmt_time(row.running_finish_time),
                "workflowStatus":   row.workflow_status,
            })

        return res("Log Entry list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_log_entry_details(entry_id):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        lb = entry.log_book

        data = {
            "id":                  entry.id,
            "logUid":              entry.log_uid,
            "logBookId":           entry.log_book_id,
            "logBookNo":           lb.log_book_no              if lb else None,
            "partyOrderId":        lb.party_order_id           if lb else None,
            "partyOrderNo":        lb.party_order.order_no     if lb and lb.party_order else None,
            "partyName":           lb.party_order.vendor.ledger_name if lb and lb.party_order and lb.party_order.vendor else None,
            "machineryName":       lb.machinery_name           if lb else None,
            "machineryRegNo":      lb.machinery_reg_no         if lb else None,
            "projectCode":         entry.project_code,
            "runningDate":         _fmt_date(entry.running_date),
            "runningStartTime":    _fmt_time(entry.running_start_time),
            "runningFinishTime":   _fmt_time(entry.running_finish_time),
            "projectSubLocation":  entry.project_sub_location,
            "segmentLayer":        entry.segment_layer,
            "workMonitoringBy":    entry.work_monitoring_by,
            "operatorName":        entry.operator_name,
            "workflowStatus":      entry.workflow_status,
            "currentLevel":        entry.current_level,
            "locked":              entry.locked,
        }

        return res("Log Entry details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_log_entry(entry_id, data, user_id):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        if entry.locked:
            return res("Log Entry cannot be edited", [], 400)

        if entry.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback entries can be edited", [], 400)

        allowed = is_creator(entry.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not Log Entry creator", [], 403)

        if data.get("runningDate"):
            entry.running_date = data.get("runningDate")
        if data.get("runningStartTime"):
            entry.running_start_time = data.get("runningStartTime")
        if data.get("runningFinishTime"):
            entry.running_finish_time = data.get("runningFinishTime")
        if data.get("projectSubLocation"):
            entry.project_sub_location = data.get("projectSubLocation")
        if data.get("segmentLayer"):
            entry.segment_layer = data.get("segmentLayer")
        if data.get("workMonitoringBy"):
            entry.work_monitoring_by = data.get("workMonitoringBy")
        if data.get("operatorName"):
            entry.operator_name = data.get("operatorName")

        if entry.workflow_status == "Reback":
            entry.correction_sent_at = None

        entry.updated_by = user_id
        entry.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Entry updated successfully",
            {"entryId": entry.id, "logUid": entry.log_uid},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_log_entry(entry_id, submitted_by=None):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        if entry.workflow_status not in ["Draft", "Reback"]:
            return res("Log Entry already submitted", [], 400)

        if entry.workflow_status == "Reback":
            entry.current_level = 0

        first_level = get_first_approver(entry.project_code, _MODULE)

        if not first_level:
            entry.workflow_status   = "Approved"
            entry.locked            = True
            entry.approved_by       = submitted_by
            entry.submitted_at      = datetime.utcnow()
            entry.final_approved_at = datetime.utcnow()
        else:
            entry.workflow_status = f"Pending_L{first_level.level_no}"
            entry.current_level   = first_level.level_no
            entry.locked          = True
            entry.submitted_at    = datetime.utcnow()

        create_history(
            project_code = entry.project_code,
            module_code  = _MODULE,
            record_id    = entry.id,
            level_no     = entry.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        entry.submitted_by = submitted_by
        entry.updated_by   = submitted_by
        entry.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Entry submitted successfully",
            {"entryId": entry.id, "logUid": entry.log_uid, "workflowStatus": entry.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_log_entry(entry_id, approved_by=None, comments=None):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        if not entry.workflow_status.startswith("Pending"):
            return res("Log Entry not pending", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, approved_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(entry.project_code, _MODULE, entry.current_level)

        if next_level:
            create_history(
                project_code = entry.project_code,
                module_code  = _MODULE,
                record_id    = entry.id,
                level_no     = entry.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            entry.current_level   = next_level.level_no
            entry.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = entry.project_code,
                module_code  = _MODULE,
                record_id    = entry.id,
                level_no     = entry.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            entry.workflow_status   = "Approved"
            entry.locked            = True
            entry.approved_by       = approved_by
            entry.final_approved_at = datetime.utcnow()

        entry.updated_by = approved_by
        entry.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Log Entry approved successfully",
            {"entryId": entry.id, "workflowStatus": entry.workflow_status, "currentLevel": entry.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_log_entry(entry_id, reback_by=None, comments=None):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        if not entry.workflow_status.startswith("Pending"):
            return res("Log Entry not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, reback_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        entry.workflow_status    = "Reback"
        entry.locked             = False
        entry.correction_sent_at = datetime.utcnow()
        entry.updated_by         = reback_by
        entry.updated_at         = datetime.utcnow()

        create_history(
            project_code = entry.project_code,
            module_code  = _MODULE,
            record_id    = entry.id,
            level_no     = entry.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "Log Entry sent for correction",
            {"entryId": entry.id, "workflowStatus": entry.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_log_entry(entry_id, rejected_by=None, comments=None):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        if not entry.workflow_status.startswith("Pending"):
            return res("Log Entry not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, rejected_by)
        if not allowed:
            return res("You are not current approver", [], 403)

        entry.workflow_status = "Rejected"
        entry.locked          = True
        entry.status          = "Inactive"
        entry.rejected_at     = datetime.utcnow()
        entry.rejected_by     = rejected_by
        entry.updated_by      = rejected_by
        entry.updated_at      = datetime.utcnow()

        create_history(
            project_code = entry.project_code,
            module_code  = _MODULE,
            record_id    = entry.id,
            level_no     = entry.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "Log Entry rejected",
            {"entryId": entry.id, "workflowStatus": entry.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# ENTRY — 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_log_entry_history(entry_id):
    try:

        entry = LogBookEntry.query.get(entry_id)
        if not entry:
            return res("Log Entry not found", [], 404)

        rows = get_history(_MODULE, entry.id)

        data = []
        for row in rows:
            data.append({
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            })

        return res("Log Entry history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
