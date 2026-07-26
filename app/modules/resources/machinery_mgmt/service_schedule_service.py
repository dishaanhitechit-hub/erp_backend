from datetime import datetime

from app.extensions import db
from app.response import res
from app.models.pmMaster import PMServiceSchedule, PMMaster


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _serialize(s: PMServiceSchedule):
    return {
        "id":                s.id,
        "pmId":              s.pm_id,
        "pmUid":             s.pm.pm_uid if s.pm else None,
        "pmName":            s.pm.machine_name if s.pm else None,
        "machineType":       s.pm.machinery_type if s.pm else None,
        "serviceType":       s.service_type,
        "serviceDate":       s.service_date.isoformat() if s.service_date else None,
        "readingUnder":      s.reading_under,
        "expectedExpenses":  float(s.expected_expenses) if s.expected_expenses else None,
        "responsiblePerson": s.responsible_person,
        "status":            s.status,
        "createdAt":         s.created_at.isoformat() if s.created_at else None,
        "updatedAt":         s.updated_at.isoformat() if s.updated_at else None,
    }


# ── CREATE ────────────────────────────────────────────────────────────────────

def create_service_schedule(data, user_id):
    try:
        pm_id = data.get("pmId")
        if not pm_id:
            return res("pmId is required", [], 400)

        pm = PMMaster.query.get(pm_id)
        if not pm:
            return res("Machinery not found", [], 404)

        s = PMServiceSchedule(
            pm_id              = pm_id,
            service_type       = data.get("serviceType"),
            service_date       = _parse_date(data.get("serviceDate")),
            reading_under      = data.get("readingUnder"),
            expected_expenses  = data.get("expectedExpenses") or None,
            responsible_person = data.get("responsiblePerson"),
            created_by         = user_id,
        )

        db.session.add(s)
        db.session.commit()

        return res("Service Schedule created", {"id": s.id}, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ── LIST ──────────────────────────────────────────────────────────────────────

def get_service_schedule_list(pm_id=None):
    try:
        query = PMServiceSchedule.query.filter_by(status="Active")
        if pm_id:
            query = query.filter_by(pm_id=pm_id)
        rows = query.order_by(PMServiceSchedule.id.desc()).all()
        return res("Service Schedule list fetched", [_serialize(s) for s in rows], 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── DETAIL ────────────────────────────────────────────────────────────────────

def get_service_schedule_detail(schedule_id):
    try:
        s = PMServiceSchedule.query.get(schedule_id)
        if not s:
            return res("Service Schedule not found", [], 404)
        return res("Service Schedule fetched", _serialize(s), 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── EDIT ──────────────────────────────────────────────────────────────────────

def edit_service_schedule(schedule_id, data, user_id):
    try:
        s = PMServiceSchedule.query.get(schedule_id)
        if not s:
            return res("Service Schedule not found", [], 404)

        if data.get("serviceType"):
            s.service_type = data.get("serviceType")
        if data.get("serviceDate"):
            s.service_date = _parse_date(data.get("serviceDate"))
        if data.get("readingUnder"):
            s.reading_under = data.get("readingUnder")
        if data.get("expectedExpenses") is not None:
            s.expected_expenses = data.get("expectedExpenses") or None
        if data.get("responsiblePerson"):
            s.responsible_person = data.get("responsiblePerson")

        s.updated_by = user_id
        s.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Service Schedule updated", {"id": s.id}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
