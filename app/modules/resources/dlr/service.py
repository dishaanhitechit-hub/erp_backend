from collections import defaultdict
from datetime import datetime

from flask import g
from app.extensions import db
from app.response import res
from app.models.dlrMaster import DlrMaster, DlrItem
from app.models.manpower import ManpowerWorker
from app.models.project import Project
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

MODULE_CODE = "dlr"


# ── Helpers ───────────────────────────────────────────────────────

def _current_user():
    cu = g.current_user if hasattr(g, "current_user") else {}
    return cu.get("id"), cu.get("projectId")


def _project_code(project_id):
    if not project_id:
        return None
    p = Project.query.get(project_id)
    return p.project_code if p else None


def _check_creator():
    user_id, project_id = _current_user()
    code = _project_code(project_id)
    return is_creator(code, MODULE_CODE, user_id), user_id, code


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _calc_working_hour(start_time, finish_time, lunch_hour):
    try:
        fmt = "%H:%M"
        s = datetime.strptime(start_time.strip(), fmt)
        f = datetime.strptime(finish_time.strip(), fmt)
        delta_hrs = (f - s).total_seconds() / 3600
        wh = delta_hrs - float(lunch_hour or 0)
        return round(max(wh, 0), 2)
    except Exception:
        return 0.0


def _generate_dlr_no():
    last = DlrMaster.query.order_by(DlrMaster.id.desc()).first()
    next_num = (last.id + 1) if last else 1
    return f"DLR{next_num:04d}"


def _serialize_item(item):
    return {
        "id": item.id,
        "slNo": item.sl_no,
        "manId": item.man_id,
        "fullName": item.full_name,
        "category": item.category,
        "startTime": item.start_time,
        "finishTime": item.finish_time,
        "lunchHour": float(item.lunch_hour or 0),
        "workingHour": float(item.working_hour or 0),
        "bonusHour": float(item.bonus_hour or 0),
        "totalWorkingHr": float(item.total_working_hr or 0),
        "jobLocation": item.job_location,
    }


def _serialize(d: DlrMaster):
    return {
        "id": d.id,
        "dlrNo": d.dlr_no,
        "dlrDate": d.dlr_date.isoformat() if d.dlr_date else None,
        "projectCode": d.project_code,
        "vendorId": d.vendor_id,
        "vendorName": d.vendor.ledger_name if d.vendor else None,
        "orderId": d.order_id,
        "reportBy": d.report_by,
        "verifiedBy": d.verified_by,
        "scanCopy": d.scan_copy,
        "workflowStatus": d.workflow_status,
        "currentLevel": d.current_level,
        "locked": d.locked,
        "createdBy": d.created_by,
        "createdAt": d.created_at.isoformat() if d.created_at else None,
        "updatedAt": d.updated_at.isoformat() if d.updated_at else None,
        "submittedAt": d.submitted_at.isoformat() if d.submitted_at else None,
        "finalApprovedAt": d.final_approved_at.isoformat() if d.final_approved_at else None,
        "rejectedAt": d.rejected_at.isoformat() if d.rejected_at else None,
        "items": [_serialize_item(i) for i in d.items],
    }


def _build_items(rows):
    items = []
    for idx, row in enumerate(rows, start=1):
        man_id = row.get("manId", "").strip()
        full_name = row.get("fullName", "").strip()
        category = row.get("category", "").strip()

        if man_id and not full_name:
            worker = ManpowerWorker.query.filter_by(man_id=man_id).first()
            if worker:
                full_name = worker.full_name
                category = category or worker.category

        start_time = row.get("startTime", "")
        finish_time = row.get("finishTime", "")
        lunch_hour = float(row.get("lunchHour") or 0)
        bonus_hour = float(row.get("bonusHour") or 0)
        working_hour = _calc_working_hour(start_time, finish_time, lunch_hour)
        total_working_hr = round(working_hour + bonus_hour, 2)

        items.append(DlrItem(
            sl_no=idx,
            man_id=man_id or None,
            full_name=full_name or None,
            category=category or None,
            start_time=start_time or None,
            finish_time=finish_time or None,
            lunch_hour=lunch_hour,
            working_hour=working_hour,
            bonus_hour=bonus_hour,
            total_working_hr=total_working_hr,
            job_location=row.get("jobLocation", "").strip() or None,
        ))
    return items


# ── CREATE ────────────────────────────────────────────────────────

def create_dlr(request):
    allowed, user_id, project_code = _check_creator()
    if not allowed:
        return res("Not authorised to create DLR", [], 403)

    data = request.form
    items_raw = request.get_json(silent=True) or {}
    items_list = items_raw.get("items", [])

    if not items_list:
        import json
        try:
            items_list = json.loads(data.get("items", "[]"))
        except Exception:
            items_list = []

    dlr_date = _parse_date(data.get("dlrDate"))
    if not dlr_date:
        return res("dlrDate is required (YYYY-MM-DD)", [], 400)

    scan_copy = None
    f = request.files.get("scanCopy")
    if f and f.filename:
        scan_copy = upload_file_to_bunny(f, folder="dlr")

    dlr = DlrMaster(
        dlr_no=_generate_dlr_no(),
        dlr_date=dlr_date,
        project_code=project_code,
        vendor_id=data.get("vendorId") or None,
        order_id=data.get("orderId") or None,
        report_by=data.get("reportBy"),
        verified_by=data.get("verifiedBy"),
        scan_copy=scan_copy,
        created_by=user_id,
    )

    db.session.add(dlr)
    db.session.flush()

    for item in _build_items(items_list):
        item.dlr_id = dlr.id
        db.session.add(item)

    db.session.commit()
    return res("DLR created", [_serialize(dlr)], 201)


# ── LIST ──────────────────────────────────────────────────────────

def get_dlr_list():
    _, project_id = _current_user()
    code = _project_code(project_id)
    query = DlrMaster.query
    if code:
        query = query.filter_by(project_code=code)
    rows = query.order_by(DlrMaster.id.desc()).all()
    return res("DLR list fetched", [_serialize(d) for d in rows], 200)


# ── DETAILS ───────────────────────────────────────────────────────

def get_dlr_details(dlr_id):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    return res("DLR fetched", [_serialize(d)], 200)


# ── EDIT ──────────────────────────────────────────────────────────

def edit_dlr(dlr_id, request):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    if d.locked or d.workflow_status not in ("Draft", "Rebacked"):
        return res("DLR cannot be edited in current status", [], 400)

    allowed, user_id, _ = _check_creator()
    if not allowed:
        return res("Not authorised to edit DLR", [], 403)

    data = request.form
    items_raw = request.get_json(silent=True) or {}
    items_list = items_raw.get("items", [])
    if not items_list:
        import json
        try:
            items_list = json.loads(data.get("items", "[]"))
        except Exception:
            items_list = []

    if data.get("dlrDate"):
        d.dlr_date = _parse_date(data.get("dlrDate"))
    if "vendorId" in data:
        d.vendor_id = data.get("vendorId") or None
    if "orderId" in data:
        d.order_id = data.get("orderId") or None
    if "reportBy" in data:
        d.report_by = data.get("reportBy")
    if "verifiedBy" in data:
        d.verified_by = data.get("verifiedBy")

    f = request.files.get("scanCopy")
    if f and f.filename:
        d.scan_copy = upload_file_to_bunny(f, folder="dlr")

    d.updated_by = user_id
    d.updated_at = datetime.utcnow()

    if items_list:
        for old in list(d.items):
            db.session.delete(old)
        db.session.flush()
        for item in _build_items(items_list):
            item.dlr_id = d.id
            db.session.add(item)

    db.session.commit()
    return res("DLR updated", [_serialize(d)], 200)


# ── SUBMIT ────────────────────────────────────────────────────────

def submit_dlr(dlr_id, user_id, project_code):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    if d.workflow_status not in ("Draft", "Rebacked"):
        return res("DLR is not in a submittable state", [], 400)
    if not is_creator(project_code, MODULE_CODE, user_id):
        return res("Not authorised to submit DLR", [], 403)

    first = get_first_approver(project_code, MODULE_CODE)
    if not first:
        return res("No approver configured for DLR", [], 400)

    d.workflow_status = f"Pending_L{first.level_no}"
    d.current_level = first.level_no
    d.submitted_by = user_id
    d.submitted_at = datetime.utcnow()
    d.locked = True

    create_history(project_code, MODULE_CODE, d.id, 0, "SUBMIT", user_id)
    db.session.commit()
    return res("DLR submitted", [_serialize(d)], 200)


# ── APPROVE ───────────────────────────────────────────────────────

def approve_dlr(dlr_id, user_id, project_code, comments=None):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    if not d.workflow_status.startswith("Pending"):
        return res("DLR is not pending approval", [], 400)
    if not is_current_approver(project_code, MODULE_CODE, d.current_level, user_id):
        return res("Not authorised to approve at this level", [], 403)

    create_history(project_code, MODULE_CODE, d.id, d.current_level, "APPROVE", user_id, comments)

    nxt = get_next_approver(project_code, MODULE_CODE, d.current_level)
    if nxt:
        d.workflow_status = f"Pending_L{nxt.level_no}"
        d.current_level = nxt.level_no
    else:
        d.workflow_status = "Approved"
        d.approved_by = user_id
        d.final_approved_at = datetime.utcnow()

    db.session.commit()
    return res("DLR approved", [_serialize(d)], 200)


# ── REBACK ────────────────────────────────────────────────────────

def reback_dlr(dlr_id, user_id, project_code, comments=None):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    if not d.workflow_status.startswith("Pending"):
        return res("DLR is not pending", [], 400)
    if not is_current_approver(project_code, MODULE_CODE, d.current_level, user_id):
        return res("Not authorised to reback at this level", [], 403)

    create_history(project_code, MODULE_CODE, d.id, d.current_level, "REBACK", user_id, comments)
    d.workflow_status = "Rebacked"
    d.current_level = 0
    d.locked = False

    db.session.commit()
    return res("DLR rebacked", [_serialize(d)], 200)


# ── REJECT ────────────────────────────────────────────────────────

def reject_dlr(dlr_id, user_id, project_code, comments=None):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    if not d.workflow_status.startswith("Pending"):
        return res("DLR is not pending", [], 400)
    if not is_current_approver(project_code, MODULE_CODE, d.current_level, user_id):
        return res("Not authorised to reject at this level", [], 403)

    create_history(project_code, MODULE_CODE, d.id, d.current_level, "REJECT", user_id, comments)
    d.workflow_status = "Rejected"
    d.rejected_by = user_id
    d.rejected_at = datetime.utcnow()
    d.locked = True

    db.session.commit()
    return res("DLR rejected", [_serialize(d)], 200)


# ── HISTORY ───────────────────────────────────────────────────────

def get_dlr_history(dlr_id, project_code):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)

    rows = get_history(MODULE_CODE, dlr_id)
    steps = get_approval_steps(project_code, MODULE_CODE, d, rows)

    history = [
        {
            "id": h.id,
            "levelNo": h.level_no,
            "action": h.action,
            "actionBy": h.action_by,
            "comments": h.comments,
            "createdAt": h.created_at.isoformat() if h.created_at else None,
        }
        for h in rows
    ]

    return res("DLR history fetched", [{"history": history, "steps": steps}], 200)


# ── MY APPROVAL STATUS ────────────────────────────────────────────

def get_dlr_my_approval_status(dlr_id, user_id, project_code):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)
    status = get_my_approval_status(project_code, MODULE_CODE, d, user_id)
    return res("My approval status", [status], 200)


# ── SUMMARY ───────────────────────────────────────────────────────

def get_dlr_summary(dlr_id):
    d = DlrMaster.query.get(dlr_id)
    if not d:
        return res("DLR not found", [], 404)

    # Mandays summary grouped by category
    cat_map = defaultdict(float)
    for item in d.items:
        if item.category:
            cat_map[item.category] += float(item.total_working_hr or 0)

    mandays_summary = []
    for idx, (cat, total_hrs) in enumerate(cat_map.items(), start=1):
        worker = ManpowerWorker.query.filter_by(category=cat).first()
        rate = float(worker.rate_per_manday) if (worker and worker.rate_per_manday) else 0.0
        manday = round(total_hrs / 8, 3)
        amount = round(manday * rate, 2)
        mandays_summary.append({
            "slNo": idx,
            "category": cat,
            "totalWorkingHr": round(total_hrs, 2),
            "manday": manday,
            "rate": rate,
            "amount": amount,
        })

    # Area wise summary grouped by job_location
    loc_map = defaultdict(float)
    for item in d.items:
        if item.job_location:
            loc_map[item.job_location] += float(item.total_working_hr or 0)

    cat_rate_map = {}
    for entry in mandays_summary:
        cat_rate_map[entry["category"]] = entry["rate"]

    area_summary = []
    for idx, (loc, total_hrs) in enumerate(loc_map.items(), start=1):
        loc_items = [i for i in d.items if i.job_location == loc]
        amount = sum(
            round((float(i.total_working_hr or 0) / 8) * cat_rate_map.get(i.category, 0), 2)
            for i in loc_items
        )
        area_summary.append({
            "slNo": idx,
            "location": loc,
            "totalWorkingHr": round(total_hrs, 2),
            "amount": round(amount, 2),
        })

    total_mandays_hrs = round(sum(e["totalWorkingHr"] for e in mandays_summary), 2)
    total_mandays_amt = round(sum(e["amount"] for e in mandays_summary), 2)
    total_area_hrs = round(sum(e["totalWorkingHr"] for e in area_summary), 2)
    total_area_amt = round(sum(e["amount"] for e in area_summary), 2)

    return res("DLR summary fetched", [{
        "mandaysSummary": mandays_summary,
        "mandaysTotal": {"totalWorkingHr": total_mandays_hrs, "amount": total_mandays_amt},
        "areaSummary": area_summary,
        "areaTotal": {"totalWorkingHr": total_area_hrs, "amount": total_area_amt},
    }], 200)
