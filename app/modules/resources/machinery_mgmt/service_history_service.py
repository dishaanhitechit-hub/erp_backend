from datetime import datetime

from app.extensions import db
from app.response import res
from app.models.pmMaster import PMServiceHistory, PMMaster
from app.cloudinary_uploader import upload_file_to_bunny


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _serialize(h: PMServiceHistory):
    return {
        "id":              h.id,
        "pmId":            h.pm_id,
        "pmUid":           h.pm.pm_uid if h.pm else None,
        "pmName":          h.pm.machine_name if h.pm else None,
        "serviceType":     h.service_type,
        "serviceDate":     h.service_date.isoformat() if h.service_date else None,
        "billAmount":      float(h.bill_amount) if h.bill_amount else None,
        "partyBillNo":     h.party_bill_no,
        "partyBillFile":   h.party_bill_file,
        "serviceLocation": h.service_location,
        "jobMonitoringBy": h.job_monitoring_by,
        "operatorName":    h.operator_name,
        "status":          h.status,
        "createdAt":       h.created_at.isoformat() if h.created_at else None,
        "updatedAt":       h.updated_at.isoformat() if h.updated_at else None,
    }


# ── CREATE ────────────────────────────────────────────────────────────────────

def create_service_history(request, user_id):
    try:
        data  = request.form
        files = request.files

        pm_id = data.get("pmId")
        if not pm_id:
            return res("pmId is required", [], 400)

        pm = PMMaster.query.get(pm_id)
        if not pm:
            return res("Machinery not found", [], 404)

        party_bill_file = None
        f = files.get("partyBillFile")
        if f:
            party_bill_file = upload_file_to_bunny(f, "machinery", f"{pm.pm_uid}/service_history", "party_bill")

        h = PMServiceHistory(
            pm_id            = pm_id,
            service_type     = data.get("serviceType"),
            service_date     = _parse_date(data.get("serviceDate")),
            bill_amount      = data.get("billAmount") or None,
            party_bill_no    = data.get("partyBillNo"),
            party_bill_file  = party_bill_file,
            service_location = data.get("serviceLocation"),
            job_monitoring_by = data.get("jobMonitoringBy"),
            operator_name    = data.get("operatorName"),
            created_by       = user_id,
        )

        db.session.add(h)
        db.session.commit()

        return res("Service History created", {"id": h.id}, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ── LIST ──────────────────────────────────────────────────────────────────────

def get_service_history_list(pm_id=None):
    try:
        query = PMServiceHistory.query.filter_by(status="Active")
        if pm_id:
            query = query.filter_by(pm_id=pm_id)
        rows = query.order_by(PMServiceHistory.id.desc()).all()
        return res("Service History list fetched", [_serialize(h) for h in rows], 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── DETAIL ────────────────────────────────────────────────────────────────────

def get_service_history_detail(history_id):
    try:
        h = PMServiceHistory.query.get(history_id)
        if not h:
            return res("Service History not found", [], 404)
        return res("Service History fetched", _serialize(h), 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── EDIT ──────────────────────────────────────────────────────────────────────

def edit_service_history(history_id, request, user_id):
    try:
        h = PMServiceHistory.query.get(history_id)
        if not h:
            return res("Service History not found", [], 404)

        data  = request.form
        files = request.files

        if data.get("serviceType"):
            h.service_type = data.get("serviceType")
        if data.get("serviceDate"):
            h.service_date = _parse_date(data.get("serviceDate"))
        if data.get("billAmount") is not None:
            h.bill_amount = data.get("billAmount") or None
        if data.get("partyBillNo"):
            h.party_bill_no = data.get("partyBillNo")
        if data.get("serviceLocation"):
            h.service_location = data.get("serviceLocation")
        if data.get("jobMonitoringBy"):
            h.job_monitoring_by = data.get("jobMonitoringBy")
        if data.get("operatorName"):
            h.operator_name = data.get("operatorName")

        f = files.get("partyBillFile")
        if f:
            pm = PMMaster.query.get(h.pm_id)
            uid = pm.pm_uid if pm else str(h.pm_id)
            h.party_bill_file = upload_file_to_bunny(f, "machinery", f"{uid}/service_history", "party_bill")

        h.updated_by = user_id
        h.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Service History updated", {"id": h.id}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
