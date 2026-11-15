"""
MIS — Follow-up board (agendas handed from person to person, Scrum / sprint style).

Flow
  Supervisor creates an agenda (+ optional first assignee)  → board "To Do", step 1 Pending
  Assignee starts                                          → step In Progress, board "In Progress"
  Assignee hands off to a project member                   → step Done, step n+1 Pending (WhatsApp)
  Assignee returns to supervisor                           → step Done, board "Review" (WhatsApp)
  Supervisor closes                                        → board "Done"
  Supervisor rejects (from Review)                         → rework step (is_rework), board "In Progress"
  Supervisor reassigns anytime                             → active step "Reassigned", new step

Who
  * supervisor: the agenda's supervisor, anyone with task_tracker.EDIT in its project, super admin
  * viewer:     anyone involved (supervisor, creator, any step assignee), task_tracker.VIEW holders
  * next person in a relay: any member of the same project (company-level: any active user)
"""
from datetime import date, datetime

from sqlalchemy import or_, exists, and_

from app.extensions import db
from app.response import res
from app.models.user import User
from app.models.misFollowup import (
    MisFollowup, MisFollowupStep, MisSprint, BOARD_STATUSES, FU_PRIORITIES, STEP_ACTIVE,
)
from app.modules.mis.common import (
    MisError, api, uid, parse_date, parse_int, choice, project_by_code, active_user,
    board_perm, board_projects, can_supervise_project, check_assignee,
    project_member_ids, log_activity, activity_for, notify,
)

ENTITY = "followup"
LINK = "/task-management/task-tracker?agenda={uuid}"


# ─────────────────────────────── access ────────────────────────────────

def _involved_ids(f):
    return {f.supervisor_user_id, f.created_by} | {s.assignee_user_id for s in f.steps}


def _can_supervise(f, user_id):
    return user_id == f.supervisor_user_id or board_perm(user_id, f.project_id, "EDIT") \
        or (f.project_id is None and user_id == f.created_by)


def _can_view(f, user_id):
    return user_id in _involved_ids(f) or board_perm(user_id, f.project_id, "VIEW")


def _get(fid, user_id, for_update=False):
    q = MisFollowup.query.filter(MisFollowup.id == fid, MisFollowup.is_deleted.is_(False))
    if for_update:
        q = q.with_for_update()
    f = q.first()
    if not f or not _can_view(f, user_id):
        raise MisError("Follow-up not found", 404)
    return f


def _require_supervisor(f, user_id):
    if not _can_supervise(f, user_id):
        raise MisError("Only the supervisor can do this", 403)


def _require_current(f, user_id):
    step = f.active_step
    if not step:
        raise MisError("Nobody is working on this right now")
    if step.assignee_user_id != user_id:
        raise MisError(f"This is with {step.assignee.username if step.assignee else 'someone else'} now", 403)
    return step


def _sprint_for(sprint_id, project_id, user_id):
    if sprint_id in (None, "", "backlog"):
        return None
    s = MisSprint.query.filter_by(id=parse_int(sprint_id, "sprintId"), is_deleted=False).first()
    if not s:
        raise MisError("Sprint not found", 404)
    if s.status == "Closed":
        raise MisError("That sprint is closed")
    if s.project_id != project_id:
        raise MisError("The sprint belongs to a different project")
    return s


# ─────────────────────────────── steps ─────────────────────────────────

def _new_step(f, assignee, by_id, instruction=None, due=None, rework=False):
    check_assignee(assignee, f.project_id)
    seq = (max((s.seq_no for s in f.steps), default=0)) + 1
    st = MisFollowupStep(followup=f, seq_no=seq, assignee_user_id=assignee.id, assigned_by=by_id,
                         instruction=(instruction or None), due_date=due, is_rework=rework,
                         assigned_at=datetime.utcnow(), status="Pending")
    db.session.add(st)
    return st


def _notify_assignee(f, step, actor_id, state):
    notify(step.assignee_user_id, title=f.title, code=f"{f.fu_code} · Step {step.seq_no}"
           + (f" · Due {step.due_date.strftime('%d-%m-%Y')}" if step.due_date else ""),
           priority=f.priority, project=f.project, actor_id=actor_id, state=state,
           link_path=LINK.format(uuid=f.fu_uuid), module_code="mis_followup", record_id=f.id,
           event="ASSIGNED")


def _step_payload(data, prefix=""):
    """Common next-assignee fields: assigneeUserId, instruction, dueDate."""
    return (
        data.get(f"{prefix}assigneeUserId") or data.get("nextAssigneeUserId"),
        (data.get("instruction") or "").strip() or None,
        parse_date(data.get("stepDueDate") or data.get("dueDate"), "dueDate"),
    )


def _detail(f, user_id):
    out = f.to_dict(with_steps=True)
    cur = f.active_step
    out["activity"] = activity_for(ENTITY, f.id)
    out["canSupervise"] = _can_supervise(f, user_id)
    out["isMyTurn"] = bool(cur and cur.assignee_user_id == user_id)
    return out


# ─────────────────────────────── list / read ───────────────────────────

def _scoped(user_id, scope):
    q = MisFollowup.query.filter(MisFollowup.is_deleted.is_(False))
    active_mine = exists().where(and_(MisFollowupStep.followup_id == MisFollowup.id,
                                      MisFollowupStep.assignee_user_id == user_id,
                                      MisFollowupStep.status.in_(STEP_ACTIVE)))
    any_mine = exists().where(and_(MisFollowupStep.followup_id == MisFollowup.id,
                                   MisFollowupStep.assignee_user_id == user_id))
    involved = or_(MisFollowup.supervisor_user_id == user_id, MisFollowup.created_by == user_id, any_mine)

    if scope == "mine":                        # waiting on me
        return q.filter(active_mine)
    if scope == "supervised":
        return q.filter(MisFollowup.supervisor_user_id == user_id)
    if scope == "involved":
        return q.filter(involved)
    if scope in ("board", "all"):              # whole board I may see
        pids = board_projects(user_id, "VIEW")
        if pids is None:
            return q
        conds = [involved]
        if pids:
            conds.append(MisFollowup.project_id.in_(pids))
        return q.filter(or_(*conds))
    raise MisError("scope must be mine, supervised, involved or board")


@api
def list_followups(args, user_id):
    user_id = uid(user_id)
    q = _scoped(user_id, (args.get("scope") or "board").strip())

    code = args.get("projectCode")
    if code:
        p = project_by_code(code)
        q = q.filter(MisFollowup.project_id == p.id) if p else q.filter(MisFollowup.project_id.is_(None))
    if str(args.get("backlog", "")).lower() in ("1", "true"):
        q = q.filter(MisFollowup.sprint_id.is_(None))
    elif args.get("sprintId"):
        q = q.filter(MisFollowup.sprint_id == parse_int(args["sprintId"], "sprintId"))
    if args.get("boardStatus"):
        q = q.filter(MisFollowup.board_status.in_([s for s in args["boardStatus"].split(",") if s]))
    if args.get("priority"):
        q = q.filter(MisFollowup.priority.in_([s for s in args["priority"].split(",") if s]))
    if args.get("assigneeUserId"):
        a = parse_int(args["assigneeUserId"], "assigneeUserId")
        q = q.filter(exists().where(and_(MisFollowupStep.followup_id == MisFollowup.id,
                                         MisFollowupStep.assignee_user_id == a,
                                         MisFollowupStep.status.in_(STEP_ACTIVE))))
    if str(args.get("overdue", "")).lower() in ("1", "true"):
        q = q.filter(MisFollowup.board_status != "Done", MisFollowup.due_date < date.today())
    search = (args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(MisFollowup.title.ilike(like), MisFollowup.fu_code.ilike(like),
                         MisFollowup.description.ilike(like)))

    page = parse_int(args.get("page") or 1, "page", minimum=1)
    per_page = min(parse_int(args.get("perPage") or 100, "perPage", minimum=1), 300)
    total = q.count()
    rows = (q.order_by(db.case((MisFollowup.board_status == "Done", 1), else_=0),
                       MisFollowup.due_date.is_(None), MisFollowup.due_date.asc(), MisFollowup.id.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    return res("ok", {"items": [f.to_dict() for f in rows], "total": total, "page": page, "perPage": per_page})


@api
def get_followup(fid, user_id):
    user_id = uid(user_id)
    return res("ok", _detail(_get(fid, user_id), user_id))


@api
def get_by_uuid(fu_uuid, user_id):
    user_id = uid(user_id)
    f = MisFollowup.query.filter_by(fu_uuid=fu_uuid, is_deleted=False).first()
    if not f or not _can_view(f, user_id):
        raise MisError("Follow-up not found", 404)
    return res("ok", _detail(f, user_id))


@api
def stats(args, user_id):
    user_id = uid(user_id)
    today = date.today()
    mine = _scoped(user_id, "mine").count()
    mine_overdue = _scoped(user_id, "mine").filter(exists().where(and_(
        MisFollowupStep.followup_id == MisFollowup.id, MisFollowupStep.assignee_user_id == user_id,
        MisFollowupStep.status.in_(STEP_ACTIVE), MisFollowupStep.due_date < today))).count()
    review = _scoped(user_id, "supervised").filter(MisFollowup.board_status == "Review").count()
    return res("ok", {"waitingOnMe": mine, "waitingOnMeOverdue": mine_overdue, "toReview": review})


@api
def my_access(user_id):
    user_id = uid(user_id)
    from app.models.project import Project
    sup = board_projects(user_id, "EDIT")
    view = board_projects(user_id, "VIEW")
    codes = lambda ids: [p.project_code for p in Project.query.filter(Project.id.in_(ids)).all()] if ids else []  # noqa: E731
    return res("ok", {
        "isSuperAdmin": sup is None,
        "superviseProjects": None if sup is None else codes(sup),
        "viewProjects": None if view is None else codes(view),
        "canSuperviseCompany": can_supervise_project(user_id, None),
    })


@api
def assignable_users(args, user_id):
    """People a step can go to: members of the project (company level: every active user)."""
    uid(user_id)
    project = project_by_code(args.get("projectCode"))
    q = User.query.filter(or_(User.is_active.is_(True), User.is_active.is_(None)))
    if project:
        q = q.filter(User.id.in_(project_member_ids(project.id) or {-1}))
    return res("ok", [{"id": u.id, "name": u.username, "empCode": u.emp_code}
                      for u in q.order_by(User.username.asc()).all()])


# ─────────────────────────────── create / edit ─────────────────────────

def _apply_fields(f, data):
    if "title" in data:
        t = (data.get("title") or "").strip()
        if not t:
            raise MisError("Title is required")
        if len(t) > 200:
            raise MisError("Title is too long (max 200)")
        f.title = t
    if "description" in data:
        f.description = data.get("description") or None
    if "priority" in data:
        f.priority = choice(data["priority"], FU_PRIORITIES, "priority")
    if "dueDate" in data:
        f.due_date = parse_date(data["dueDate"], "dueDate")
    if "storyPoints" in data:
        f.story_points = parse_int(data["storyPoints"], "storyPoints", minimum=0)


@api
def create_followup(data, user_id):
    user_id = uid(user_id)
    project = project_by_code(data.get("projectCode"))
    pid = project.id if project else None
    if not can_supervise_project(user_id, pid):
        raise MisError("Only a supervisor (Task Tracker edit permission) can create follow-ups here", 403)
    if "title" not in data:
        raise MisError("Title is required")

    supervisor_id = user_id
    if data.get("supervisorUserId") not in (None, ""):
        sup = active_user(data["supervisorUserId"], "Supervisor")
        check_assignee(sup, pid)
        supervisor_id = sup.id

    sprint = _sprint_for(data.get("sprintId"), pid, user_id)
    f = MisFollowup(project_id=pid, supervisor_user_id=supervisor_id, created_by=user_id,
                    sprint_id=sprint.id if sprint else None, priority="Medium",
                    board_status="To Do" if sprint else "Backlog")
    _apply_fields(f, {k: data[k] for k in ("title", "description", "priority", "dueDate", "storyPoints") if k in data})
    db.session.add(f)
    db.session.flush()
    f.fu_code = f"FU-{date.today().year}-{f.id:05d}"
    log_activity(ENTITY, f.id, user_id, "CREATED", new=f.title)

    step = None
    if data.get("assigneeUserId"):
        assignee = active_user(data["assigneeUserId"], "Assignee")
        step = _new_step(f, assignee, user_id, (data.get("instruction") or "").strip(),
                         parse_date(data.get("stepDueDate"), "stepDueDate") or f.due_date)
        if f.board_status == "Backlog":
            f.board_status = "To Do"
        log_activity(ENTITY, f.id, user_id, "ASSIGNED", new=assignee.username, comment=step.instruction)
    db.session.commit()
    if step:
        _notify_assignee(f, step, user_id, "Step 1 assigned")
    return res("Follow-up created", _detail(f, user_id), 201)


@api
def update_followup(fid, data, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    before = (f.title, f.priority, f.due_date, f.story_points)
    _apply_fields(f, {k: data[k] for k in ("title", "description", "priority", "dueDate", "storyPoints") if k in data})
    if data.get("supervisorUserId") not in (None, ""):
        sup = active_user(data["supervisorUserId"], "Supervisor")
        check_assignee(sup, f.project_id)
        if sup.id != f.supervisor_user_id:
            log_activity(ENTITY, f.id, user_id, "SUPERVISOR", old=f.supervisor.username if f.supervisor else None,
                         new=sup.username)
            f.supervisor_user_id = sup.id
    if (f.title, f.priority, f.due_date, f.story_points) != before:
        log_activity(ENTITY, f.id, user_id, "UPDATED")
    db.session.commit()
    return res("Follow-up updated", _detail(f, user_id))


@api
def move_sprint(fid, data, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    sprint = _sprint_for(data.get("sprintId"), f.project_id, user_id)
    old = f.sprint.name if f.sprint else "Backlog"
    f.sprint_id = sprint.id if sprint else None
    if sprint and f.board_status == "Backlog":
        f.board_status = "To Do"
    elif not sprint and f.board_status == "To Do" and f.active_step is None:
        f.board_status = "Backlog"
    log_activity(ENTITY, f.id, user_id, "SPRINT", old=old, new=sprint.name if sprint else "Backlog")
    db.session.commit()
    return res("Moved", _detail(f, user_id))


@api
def set_board_status(fid, data, user_id):
    """
    Drag between columns (supervisor). Moves that would break the relay are refused:
      Backlog / To Do  – only while nobody has started
      In Progress      – needs someone assigned
      Review           – only when nobody holds it
      Done             – closes it (cancels an active step)
    """
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    new = choice(data.get("boardStatus"), BOARD_STATUSES, "boardStatus")
    old = f.board_status
    if new == old:
        return res("No change", _detail(f, user_id))
    cur = f.active_step

    if new == "Done":
        return _close(f, user_id, data.get("note"))
    if new in ("Backlog", "To Do"):
        if cur and cur.status == "In Progress":
            raise MisError(f"{cur.assignee.username} has already started — reassign or close instead")
        if any(s.status == "Done" for s in f.steps):
            raise MisError("Work has already been handed off — it cannot go back to " + new)
    elif new == "In Progress":
        if not cur:
            raise MisError("Assign someone first")
        # the step itself is only started by its assignee (keeps the pick-up time honest)
    elif new == "Review":
        if cur:
            raise MisError(f"{cur.assignee.username} still has it — they return it, or reassign")
    if old == "Done":
        f.closed_at = None
    f.board_status = new
    log_activity(ENTITY, f.id, user_id, "STATUS", old=old, new=new)
    db.session.commit()
    return res("Moved", _detail(f, user_id))


@api
def delete_followup(fid, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    f.is_deleted = True
    for s in f.steps:
        if s.status in STEP_ACTIVE:
            s.status = "Cancelled"
    log_activity(ENTITY, f.id, user_id, "DELETED")
    db.session.commit()
    return res("Follow-up deleted", [])


@api
def add_comment(fid, data, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id)
    text = (data.get("comment") or "").strip()
    if not text:
        raise MisError("comment is required")
    log_activity(ENTITY, f.id, user_id, "COMMENT", comment=text[:2000])
    db.session.commit()
    return res("Comment added", [], 201)


# ─────────────────────────────── relay actions ─────────────────────────

@api
def assign(fid, data, user_id):
    """Supervisor assigns (no one has it) or reassigns (someone has it)."""
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    if f.board_status == "Done":
        raise MisError("This follow-up is closed")
    to_id, instruction, due = _step_payload(data)
    assignee = active_user(to_id, "Assignee")
    cur = f.active_step
    if cur and cur.assignee_user_id == assignee.id:
        raise MisError(f"It is already with {assignee.username}")
    if cur:
        cur.status = "Reassigned"
        cur.completed_at = datetime.utcnow()
    step = _new_step(f, assignee, user_id, instruction, due or f.due_date)
    if f.board_status in ("Backlog", "Review"):
        f.board_status = "To Do" if not any(s.status == "Done" for s in f.steps) else "In Progress"
    log_activity(ENTITY, f.id, user_id, "ASSIGNED", old=cur.assignee.username if cur else None,
                 new=assignee.username, comment=instruction)
    db.session.commit()
    _notify_assignee(f, step, user_id, f"Step {step.seq_no} assigned")
    return res("Assigned", _detail(f, user_id))


@api
def start(fid, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    step = _require_current(f, user_id)
    if step.status == "In Progress":
        return res("Already started", _detail(f, user_id))
    step.status, step.started_at = "In Progress", datetime.utcnow()
    old = f.board_status
    f.board_status = "In Progress"
    log_activity(ENTITY, f.id, user_id, "STARTED", old=old, new="In Progress")
    db.session.commit()
    return res("Started", _detail(f, user_id))


@api
def handoff(fid, data, user_id):
    """Current assignee finishes their part and passes it to the next project member."""
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    step = _require_current(f, user_id)
    to_id, instruction, due = _step_payload(data)
    if not to_id:
        raise MisError("Choose who gets it next (or return it to the supervisor)")
    nxt = active_user(to_id, "Next person")
    if nxt.id == user_id:
        raise MisError("You cannot hand it to yourself")
    check_assignee(nxt, f.project_id)

    now = datetime.utcnow()
    step.status, step.completed_at = "Done", now
    step.started_at = step.started_at or now
    step.completion_note = (data.get("note") or "").strip() or None
    new_step = _new_step(f, nxt, user_id, instruction, due)
    f.board_status = "In Progress"
    log_activity(ENTITY, f.id, user_id, "HANDOFF", old=step.assignee.username if step.assignee else None,
                 new=nxt.username, comment=step.completion_note)
    db.session.commit()
    _notify_assignee(f, new_step, user_id, f"Handed over (step {new_step.seq_no})")
    return res(f"Handed to {nxt.username}", _detail(f, user_id))


@api
def return_to_supervisor(fid, data, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    step = _require_current(f, user_id)
    now = datetime.utcnow()
    step.status, step.completed_at = "Done", now
    step.started_at = step.started_at or now
    step.completion_note = (data.get("note") or "").strip() or None
    f.board_status = "Review"
    log_activity(ENTITY, f.id, user_id, "RETURNED", new="Review", comment=step.completion_note)
    db.session.commit()
    if f.supervisor_user_id != user_id:
        notify(f.supervisor_user_id, title=f.title, code=f"{f.fu_code} · Review", priority=f.priority,
               project=f.project, actor_id=user_id, state="Ready for review",
               link_path=LINK.format(uuid=f.fu_uuid), module_code="mis_followup", record_id=f.id,
               event="RETURNED")
    return res("Returned to supervisor", _detail(f, user_id))


def _close(f, user_id, note=None):
    for s in f.steps:
        if s.status in STEP_ACTIVE:
            s.status = "Cancelled"
            s.completed_at = datetime.utcnow()
    old = f.board_status
    f.board_status = "Done"
    f.closed_at = datetime.utcnow()
    log_activity(ENTITY, f.id, user_id, "CLOSED", old=old, new="Done", comment=(note or "").strip() or None)
    db.session.commit()
    return res("Closed", _detail(f, user_id))


@api
def close(fid, data, user_id):
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    if f.board_status == "Done":
        raise MisError("Already closed")
    return _close(f, user_id, data.get("note"))


@api
def reject(fid, data, user_id):
    """Supervisor sends it back for rework (from Review). Default: the last person who worked on it."""
    user_id = uid(user_id)
    f = _get(fid, user_id, for_update=True)
    _require_supervisor(f, user_id)
    if f.board_status != "Review":
        raise MisError("Only an item in Review can be sent back")
    note = (data.get("note") or "").strip()
    if not note:
        raise MisError("Say what needs to be fixed")
    last_done = next((s for s in reversed(f.steps) if s.status == "Done"), None)
    to_id = data.get("assigneeUserId") or (last_done.assignee_user_id if last_done else None)
    if not to_id:
        raise MisError("Choose who should fix it")
    who = active_user(to_id, "Assignee")
    if last_done and last_done.assignee_user_id == who.id:
        last_done.status = "Rejected"            # their output was not accepted
    step = _new_step(f, who, user_id, data.get("instruction") or note,
                     parse_date(data.get("dueDate"), "dueDate"), rework=True)
    f.board_status = "In Progress"
    log_activity(ENTITY, f.id, user_id, "REJECTED", new=who.username, comment=note)
    db.session.commit()
    _notify_assignee(f, step, user_id, "Sent back for rework")
    return res("Sent back for rework", _detail(f, user_id))
