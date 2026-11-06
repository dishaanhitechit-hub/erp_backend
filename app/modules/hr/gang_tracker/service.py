from datetime import date, datetime
from app.extensions import db
from app.response import res
from app.models.gang_tracker import GangMember, GangFollowupLog


def _today():
    return date.today()


# ── list ─────────────────────────────────────────────────────────────────────
def list_members(params):
    q = GangMember.query

    search = (params.get("search") or "").strip()
    if search:
        q = q.filter(
            db.or_(
                GangMember.name.ilike(f"%{search}%"),
                GangMember.skill.ilike(f"%{search}%"),
                GangMember.location.ilike(f"%{search}%"),
                GangMember.site.ilike(f"%{search}%"),
            )
        )

    status = (params.get("status") or "").strip()
    if status:
        q = q.filter(GangMember.status == status)

    skill = (params.get("skill") or "").strip()
    if skill:
        q = q.filter(GangMember.skill == skill)

    members = q.order_by(GangMember.name).all()
    return res("ok", [m.to_dict() for m in members])


# ── get one ───────────────────────────────────────────────────────────────────
def get_member(member_id):
    m = GangMember.query.get(member_id)
    if not m:
        return res("Member not found", {}, 404)
    return res("ok", m.to_dict())


# ── create ────────────────────────────────────────────────────────────────────
def create_member(data, user_id=None):
    name   = (data.get("name") or "").strip()
    mobile = (data.get("mobile") or "").strip()
    if not name or not mobile:
        return res("name and mobile are required", {}, 400)

    followup = None
    if data.get("followup"):
        try:
            followup = datetime.strptime(data["followup"], "%Y-%m-%d").date()
        except ValueError:
            pass

    m = GangMember(
        name=name,
        skill=data.get("skill"),
        mobile=mobile,
        whatsapp=data.get("whatsapp"),
        location=data.get("location"),
        status=data.get("status", "Available"),
        site=data.get("site"),
        followup_date=followup,
        notes=data.get("notes"),
        created_by=user_id,
    )
    db.session.add(m)
    db.session.flush()

    if data.get("notes"):
        log = GangFollowupLog(member_id=m.id, log_date=_today(), note=data["notes"])
        db.session.add(log)

    db.session.commit()
    return res("Member created", m.to_dict(), 201)


# ── update ────────────────────────────────────────────────────────────────────
def update_member(member_id, data):
    m = GangMember.query.get(member_id)
    if not m:
        return res("Member not found", {}, 404)

    for field in ("name", "skill", "mobile", "whatsapp", "location", "status", "site", "notes"):
        if field in data:
            setattr(m, field, (data[field] or "").strip() if isinstance(data[field], str) else data[field])

    if "followup" in data:
        if data["followup"]:
            try:
                m.followup_date = datetime.strptime(data["followup"], "%Y-%m-%d").date()
            except ValueError:
                pass
        else:
            m.followup_date = None

    db.session.commit()
    return res("Member updated", m.to_dict())


# ── delete ────────────────────────────────────────────────────────────────────
def delete_member(member_id):
    m = GangMember.query.get(member_id)
    if not m:
        return res("Member not found", {}, 404)
    db.session.delete(m)
    db.session.commit()
    return res("Member deleted", {})


# ── add follow-up log ─────────────────────────────────────────────────────────
def add_followup(member_id, data):
    m = GangMember.query.get(member_id)
    if not m:
        return res("Member not found", {}, 404)

    note       = (data.get("note") or "").strip()
    new_status = (data.get("status") or "").strip()
    new_date   = (data.get("followup") or "").strip()

    if not note and not new_status and not new_date:
        return res("Provide at least note, status, or followup date", {}, 400)

    if note:
        log = GangFollowupLog(member_id=m.id, log_date=_today(), note=note)
        db.session.add(log)

    if new_status:
        m.status = new_status

    if new_date:
        try:
            m.followup_date = datetime.strptime(new_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    db.session.commit()
    return res("Follow-up saved", m.to_dict())


# ── skills list ───────────────────────────────────────────────────────────────
def list_skills():
    rows = db.session.query(GangMember.skill).filter(GangMember.skill.isnot(None)).distinct().all()
    return res("ok", sorted(r[0] for r in rows))
