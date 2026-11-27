"""Gang Tracker conversations: a topic that moves between people, logged step by step.

A person can be passed as {"id": 5}, 5, {"name": "Ravi", "mobile": "..."} or "Ravi".
A name that is not on the register yet is auto-registered as a gang member, so it
shows up in the pickers next time.
"""
from datetime import date, datetime

from app.extensions import db
from app.response import res
from app.models.gang_tracker import (
    GangMember, GangThread, GangThreadEntry, THREAD_STATUSES, CLOSED_STATUSES,
)


def _parse_date(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_person(raw, user_id=None):
    """Return a GangMember (existing or auto-registered) or None. Raises ValueError on a bad id."""
    if raw in (None, "", {}):
        return None
    if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()):
        raw = {"id": int(raw)}
    if isinstance(raw, str):
        raw = {"name": raw}
    if raw.get("id"):
        m = db.session.get(GangMember, int(raw["id"]))
        if not m:
            raise ValueError(f"Person #{raw['id']} not found")
        return m
    name = " ".join((raw.get("name") or "").split())
    if not name:
        return None
    m = GangMember.query.filter(db.func.lower(GangMember.name) == name.lower()).order_by(GangMember.id).first()
    if m:
        return m
    m = GangMember(name=name, mobile=(raw.get("mobile") or "").strip() or None, skill=raw.get("skill") or None,
                   status="Follow-up", created_by=user_id)
    db.session.add(m)
    db.session.flush()
    return m


def _apply_step(thread, data, user_id, first=False):
    """Append one entry to the thread and move the thread's 'next step' fields forward."""
    person   = _resolve_person(data.get("person"), user_id)
    referred = _resolve_person(data.get("referredTo"), user_id)
    next_p   = _resolve_person(data.get("nextPerson"), user_id)
    note     = (data.get("note") or "").strip() or None
    next_on  = _parse_date(data.get("nextFollowup"))
    action   = (data.get("nextAction") or "").strip()[:300] or None
    status   = (data.get("status") or "").strip()

    if status and status not in THREAD_STATUSES:
        raise ValueError(f"status must be one of {', '.join(THREAD_STATUSES)}")
    if first and not person:
        raise ValueError("Who did you talk to? (person is required)")
    if not (note or status or next_on or referred):
        raise ValueError("Add what was discussed, a next follow-up, a referral or a status")

    # a follow-up date with no one named means "back to the same person"
    if next_on and not next_p:
        next_p = person or thread.next_member
    if not status:
        status = "Scheduled" if next_on else ("Waiting" if referred else "Ongoing")

    entry = GangThreadEntry(
        thread=thread, entry_date=_parse_date(data.get("date")) or date.today(),
        member=person, note=note, referred_to=referred, next_member=next_p,
        next_followup_date=next_on, next_action=action, status_after=status, created_by=user_id,
    )
    db.session.add(entry)

    thread.status = status
    if status in CLOSED_STATUSES:
        thread.closed_at = datetime.utcnow()
        thread.next_member, thread.next_followup_date, thread.next_action = None, None, None
    else:
        thread.closed_at = None
        thread.next_member = next_p or referred or person or thread.next_member
        thread.next_followup_date = next_on
        thread.next_action = action or (f"Connect with {referred.name}" if referred and not next_on else None)
    thread.updated_at = datetime.utcnow()
    return entry


# ── list ─────────────────────────────────────────────────────────────────────
def list_threads(params):
    q = GangThread.query
    search = (params.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        people = db.session.query(GangThreadEntry.thread_id).join(
            GangMember, db.or_(GangMember.id == GangThreadEntry.member_id,
                               GangMember.id == GangThreadEntry.referred_to_id)
        ).filter(GangMember.name.ilike(like))
        q = q.filter(db.or_(GangThread.topic.ilike(like), GangThread.project.ilike(like),
                            GangThread.next_action.ilike(like), GangThread.id.in_(people)))

    status = (params.get("status") or "").strip()
    if status == "open":
        q = q.filter(GangThread.status.notin_(CLOSED_STATUSES))
    elif status:
        q = q.filter(GangThread.status == status)

    project = (params.get("project") or "").strip()
    if project:
        q = q.filter(GangThread.project == project)

    member_id = params.get("memberId")
    if member_id and str(member_id).isdigit():
        mid = int(member_id)
        q = q.filter(GangThread.id.in_(db.session.query(GangThreadEntry.thread_id).filter(db.or_(
            GangThreadEntry.member_id == mid, GangThreadEntry.referred_to_id == mid,
            GangThreadEntry.next_member_id == mid))))

    due = params.get("due")
    if due in ("today", "overdue"):
        op = (GangThread.next_followup_date == date.today()) if due == "today" else (GangThread.next_followup_date < date.today())
        q = q.filter(op, GangThread.status.notin_(CLOSED_STATUSES))

    rows = q.order_by(GangThread.updated_at.desc()).all()
    return res("ok", [t.to_dict() for t in rows])


def get_thread(thread_id):
    t = db.session.get(GangThread, thread_id)
    if not t:
        return res("Conversation not found", {}, 404)
    return res("ok", t.to_dict(with_entries=True))


# ── create / add step ────────────────────────────────────────────────────────
def new_thread(data, user_id=None):
    """Build a conversation + its first talk in the session (no commit). Raises ValueError on bad input."""
    topic = " ".join((data.get("topic") or "").split())[:300]
    if not topic:
        raise ValueError("Topic / agenda is required")
    t = GangThread(topic=topic, project=(data.get("project") or "").strip()[:200] or None, created_by=user_id)
    db.session.add(t)
    entry = _apply_step(t, data, user_id, first=True)
    t.started_with = entry.member
    return t


def create_thread(data, user_id=None):
    try:
        t = new_thread(data, user_id)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), {}, 400)
    db.session.commit()
    return res("Conversation started", t.to_dict(with_entries=True), 201)


def add_entry(thread_id, data, user_id=None):
    t = db.session.get(GangThread, thread_id)
    if not t:
        return res("Conversation not found", {}, 404)
    try:
        _apply_step(t, data, user_id)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), {}, 400)
    db.session.commit()
    db.session.refresh(t)
    return res("Update saved", t.to_dict(with_entries=True))


def update_thread(thread_id, data):
    """Edit the heading only (topic / project). History stays append-only."""
    t = db.session.get(GangThread, thread_id)
    if not t:
        return res("Conversation not found", {}, 404)
    if "topic" in data:
        topic = " ".join((data.get("topic") or "").split())[:300]
        if not topic:
            return res("Topic / agenda is required", {}, 400)
        t.topic = topic
    if "project" in data:
        t.project = (data.get("project") or "").strip()[:200] or None
    db.session.commit()
    return res("Conversation updated", t.to_dict(with_entries=True))


def delete_thread(thread_id):
    t = db.session.get(GangThread, thread_id)
    if not t:
        return res("Conversation not found", {}, 404)
    db.session.delete(t)
    db.session.commit()
    return res("Conversation deleted", {})


# ── pickers ──────────────────────────────────────────────────────────────────
def list_people(params):
    """Light list for the person picker (every registered name, incl. auto-registered ones)."""
    q = GangMember.query
    search = (params.get("search") or "").strip()
    if search:
        q = q.filter(db.or_(GangMember.name.ilike(f"%{search}%"), GangMember.mobile.ilike(f"%{search}%")))
    rows = q.order_by(GangMember.name).limit(500).all()
    return res("ok", [{"id": m.id, "name": m.name, "skill": m.skill, "mobile": m.mobile, "location": m.location}
                      for m in rows])


def list_thread_projects():
    """Project names used in past conversations (the page merges these with the project master)."""
    rows = db.session.query(GangThread.project).filter(GangThread.project.isnot(None)).distinct().all()
    return res("ok", sorted({r[0] for r in rows if r[0]}, key=str.lower))
