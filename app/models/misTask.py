# app/models/misTask.py
# MIS — Self Task + shared activity log (also used later by follow-ups).
import os
import uuid as _uuid
from datetime import datetime, time as _time, timezone
from zoneinfo import ZoneInfo

from app.extensions import db

TASK_STATUSES = ("To Do", "In Progress", "On Hold", "Done", "Cancelled")
OPEN_STATUSES = ("To Do", "In Progress", "On Hold")
# Immediate = do now; Scheduled = do on its planned date. Older Low/Medium/High/Critical rows were
# migrated (High/Critical → Immediate, Low/Medium → Scheduled) in the mis_task_priority_handover migration.
TASK_PRIORITIES = ("Immediate", "Scheduled")
DEFAULT_PRIORITY = "Scheduled"
REOPEN_STATUSES = ("Pending", "Approved", "Rejected")

# ── Boards (Azure Boards style, Scrum process) ──────────────────────────────
# Every existing mis_tasks row is a "Task" with no parent / sprint, so the Self
# Task page keeps working unchanged. Hierarchy: Epic → Feature → PBI → Task/Bug.
WORK_ITEM_TYPES = ("Epic", "Feature", "PBI", "Bug", "Task")
WI_STATES = {
    "Epic": ("New", "In Progress", "Done", "Removed"),
    "Feature": ("New", "In Progress", "Done", "Removed"),
    "PBI": ("New", "Approved", "Committed", "Done", "Removed"),
    "Bug": ("New", "Approved", "Committed", "Done", "Removed"),
    "Task": TASK_STATUSES,
}
WI_DEFAULT_STATE = {"Epic": "New", "Feature": "New", "PBI": "New", "Bug": "New", "Task": "To Do"}
# allowed parent type(s) per child type (no parent is always allowed)
WI_PARENT_TYPES = {
    "Epic": (),
    "Feature": ("Epic",),
    "PBI": ("Feature",),
    "Bug": ("Feature",),
    "Task": ("PBI", "Bug"),
}
# ID prefix for NEW items (construction names). Items created before 2026-11-27 keep their old codes
# (EPC-, FEA-, PBI-, BUG-); a code never changes after creation — not even when an Activity becomes a Snag.
WI_CODE_PREFIX = {"Epic": "PHS", "Feature": "WPK", "PBI": "ACT", "Bug": "SNG", "Task": "TSK"}
# Construction names shown to users (messages, WhatsApp). Keys stay as stored; keep in step with
# TYPE_LABEL in erp-frontend src/lib/misBoards.js and typeLabel in erp_mobile sprint_board_screen.dart.
WI_LABEL = {"Epic": "Phase", "Feature": "Work Package", "PBI": "Activity", "Bug": "Snag", "Task": "Task"}

LINK_TARGET_TYPES = ("WORK_ITEM", "FOLLOWUP", "ERP_DOC")
LINK_TYPES = ("related", "predecessor", "successor")
RETRO_CATEGORIES = ("went_well", "improve", "action")

# Times typed by users (start / due time) are local office time; stored datetimes are UTC.
APP_TZ = ZoneInfo(os.getenv("APP_TIMEZONE") or "Asia/Kolkata")


def local_to_utc(d, t):
    """date + local time → naive UTC datetime (how every other timestamp is stored)."""
    return datetime.combine(d, t, tzinfo=APP_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _t(v):
    return v.strftime("%H:%M") if v else None


def _d(v):
    """Dates as YYYY-MM-DD; datetimes (stored in UTC) as ISO with a Z so browsers show local time."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v.replace(microsecond=0).isoformat() + "Z"
    return v.isoformat()


class MisTask(db.Model):
    __tablename__ = "mis_tasks"

    id = db.Column(db.Integer, primary_key=True)
    task_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True,
                          default=lambda: str(_uuid.uuid4()))
    task_code = db.Column(db.String(30), unique=True)          # TSK-2026-00001, set after flush

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)  # NULL = company-level

    priority = db.Column(db.String(20), nullable=False, default=DEFAULT_PRIORITY)
    status = db.Column(db.String(20), nullable=False, default="To Do", index=True)
    # who the finished work is handed over to (optional, informational)
    handover_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    start_date = db.Column(db.Date)
    start_time = db.Column(db.Time)                 # optional, local time
    due_date = db.Column(db.Date, index=True)
    due_time = db.Column(db.Time)                   # optional, local time (no time = end of the due day)
    completed_at = db.Column(db.DateTime)           # UTC — when it was marked Done

    # work timer (UTC). The clock runs only while status = In Progress:
    #   Start → In Progress (clock on) · On Hold (clock paused) · Done (clock stops, task locks)
    started_at = db.Column(db.DateTime)             # first time Start was pressed
    run_started_at = db.Column(db.DateTime)         # current running session (NULL = clock not running)
    worked_seconds = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # finished sessions

    estimated_hours = db.Column(db.Numeric(7, 2))
    actual_hours = db.Column(db.Numeric(7, 2))
    reopen_count = db.Column(db.Integer, nullable=False, default=0)   # feeds performance "error" score

    tags = db.Column(db.JSON)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)

    # ── Boards fields (all nullable / defaulted — existing rows = plain Task) ──
    work_item_type = db.Column(db.String(10), nullable=False, default="Task", server_default="Task", index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("mis_tasks.id"), nullable=True, index=True)
    sprint_id = db.Column(db.Integer, db.ForeignKey("mis_sprints.id"), nullable=True, index=True)  # NULL = backlog
    story_points = db.Column(db.Numeric(5, 1))          # PBI / Bug
    remaining_hours = db.Column(db.Numeric(7, 2))       # Task (burndown)
    acceptance_criteria = db.Column(db.Text)            # PBI / Bug
    backlog_rank = db.Column(db.Float, index=True)      # lower = higher on the backlog
    is_blocked = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    blocked_reason = db.Column(db.Text)
    # Kanban position (team items): which board column / lane the card sits in, and whether it is
    # in the "Done" half of a split column. NULL column = the first column mapped to its state.
    board_column = db.Column(db.String(40))
    board_column_done = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    board_lane = db.Column(db.String(40))

    # all timestamps are UTC (set in Python so the DB server's time zone does not matter)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_user_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    handover_user = db.relationship("User", foreign_keys=[handover_user_id])
    project = db.relationship("Project")
    parent = db.relationship("MisTask", remote_side=[id], backref=db.backref("children", lazy="dynamic"))
    sprint = db.relationship("MisSprint", foreign_keys=[sprint_id])

    @property
    def due_at(self):
        """Deadline as UTC datetime: due date + due time (or end of that day)."""
        if not self.due_date:
            return None
        return local_to_utc(self.due_date, self.due_time or _time(23, 59, 59))

    def live_worked_seconds(self, now=None):
        extra = 0
        if self.run_started_at:
            extra = max(0, int(((now or datetime.utcnow()) - self.run_started_at).total_seconds()))
        return (self.worked_seconds or 0) + extra

    @property
    def is_locked(self):
        return self.status == "Done"

    def is_overdue(self, today):
        if not self.due_date or self.status not in OPEN_STATUSES:
            return False
        if self.due_time:
            return datetime.utcnow() > self.due_at
        return self.due_date < today

    def to_dict(self, today=None):
        from datetime import date
        today = today or date.today()
        return {
            "id": self.id,
            "uuid": self.task_uuid,
            "taskCode": self.task_code,
            "title": self.title,
            "description": self.description,
            "ownerUserId": self.owner_user_id,
            "ownerName": self.owner.username if self.owner else None,
            "ownerEmpCode": self.owner.emp_code if self.owner else None,
            "createdBy": self.created_by,
            "createdByName": self.creator.username if self.creator else None,
            "handoverUserId": self.handover_user_id,
            "handoverName": self.handover_user.username if self.handover_user else None,
            "projectId": self.project_id,
            "projectCode": self.project.project_code if self.project else None,
            "projectName": self.project.project_name if self.project else None,
            "priority": self.priority,
            "status": self.status,
            "startDate": _d(self.start_date),
            "startTime": _t(self.start_time),
            "dueDate": _d(self.due_date),
            "dueTime": _t(self.due_time),
            "dueAt": _d(self.due_at),
            "completedAt": _d(self.completed_at),
            "startedAt": _d(self.started_at),
            "runStartedAt": _d(self.run_started_at),
            "isRunning": self.run_started_at is not None,
            "workedSeconds": self.live_worked_seconds(),
            "overEstimate": bool(self.estimated_hours and self.live_worked_seconds() > float(self.estimated_hours) * 3600),
            "isLocked": self.is_locked,
            "estimatedHours": float(self.estimated_hours) if self.estimated_hours is not None else None,
            "actualHours": float(self.actual_hours) if self.actual_hours is not None else None,
            "reopenCount": self.reopen_count or 0,
            "tags": self.tags or [],
            "isOverdue": self.is_overdue(today),
            "workItemType": self.work_item_type or "Task",
            "parentId": self.parent_id,
            "sprintId": self.sprint_id,
            "sprintName": self.sprint.name if self.sprint else None,
            "storyPoints": float(self.story_points) if self.story_points is not None else None,
            "remainingHours": float(self.remaining_hours) if self.remaining_hours is not None else None,
            "acceptanceCriteria": self.acceptance_criteria,
            "backlogRank": self.backlog_rank,
            "isBlocked": bool(self.is_blocked),
            "blockedReason": self.blocked_reason,
            "boardColumn": self.board_column,
            "boardColumnDone": bool(self.board_column_done),
            "boardLane": self.board_lane,
            "createdAt": _d(self.created_at),
            "updatedAt": _d(self.updated_at),
        }


class MisActivity(db.Model):
    """Timeline for MIS entities (entity_type: 'task' now, 'followup' later)."""
    __tablename__ = "mis_activity"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(30), nullable=False)   # CREATED | UPDATED | STATUS | ASSIGNED | COMMENT | DELETED
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    user = db.relationship("User")

    __table_args__ = (
        db.Index("ix_mis_activity_entity", "entity_type", "entity_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "userId": self.user_id,
            "userName": self.user.username if self.user else None,
            "oldValue": self.old_value,
            "newValue": self.new_value,
            "comment": self.comment,
            "createdAt": _d(self.created_at),
        }


class MisTaskReopenRequest(db.Model):
    """A Done task is locked; to work on it again the owner asks a higher level to reopen it."""
    __tablename__ = "mis_task_reopen_requests"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("mis_tasks.id"), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="Pending", index=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)
    decision_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    task = db.relationship("MisTask")
    requester = db.relationship("User", foreign_keys=[requested_by])
    decider = db.relationship("User", foreign_keys=[decided_by])

    def to_dict(self):
        t = self.task
        return {
            "id": self.id,
            "taskId": self.task_id,
            "taskCode": t.task_code if t else None,
            "taskTitle": t.title if t else None,
            "taskOwnerName": t.owner.username if t and t.owner else None,
            "requestedBy": self.requested_by,
            "requestedByName": self.requester.username if self.requester else None,
            "reason": self.reason,
            "status": self.status,
            "decidedBy": self.decided_by,
            "decidedByName": self.decider.username if self.decider else None,
            "decidedAt": _d(self.decided_at),
            "decisionNote": self.decision_note,
            "createdAt": _d(self.created_at),
        }


# ── Boards: links, capacity, burndown snapshots, retro, saved queries ───────

class MisWorkItemLink(db.Model):
    """A work item linked to another work item, a follow-up (kept separate on
    purpose) or any ERP document. Parent/child is NOT here — it is mis_tasks.parent_id."""
    __tablename__ = "mis_work_item_links"

    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(db.Integer, db.ForeignKey("mis_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = db.Column(db.String(12), nullable=False)        # WORK_ITEM | FOLLOWUP | ERP_DOC
    target_id = db.Column(db.Integer)                              # mis_tasks.id / mis_followups.id
    target_ref = db.Column(db.String(120))                         # ERP_DOC: doc kind + uuid / code
    link_type = db.Column(db.String(12), nullable=False, default="related")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    work_item = db.relationship("MisTask", foreign_keys=[work_item_id])
    creator = db.relationship("User")

    __table_args__ = (
        db.Index("ix_mis_wi_links_target", "target_type", "target_id"),
        db.UniqueConstraint("work_item_id", "target_type", "target_id", "target_ref", "link_type",
                            name="uq_mis_wi_link"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "workItemId": self.work_item_id,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "targetRef": self.target_ref,
            "linkType": self.link_type,
            "createdBy": self.created_by,
            "createdByName": self.creator.username if self.creator else None,
            "createdAt": _d(self.created_at),
        }


class MisSprintCapacity(db.Model):
    """Per-member capacity for a sprint (hours per working day, minus days off)."""
    __tablename__ = "mis_sprint_capacity"

    id = db.Column(db.Integer, primary_key=True)
    sprint_id = db.Column(db.Integer, db.ForeignKey("mis_sprints.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    hours_per_day = db.Column(db.Numeric(4, 1), nullable=False, default=6)
    days_off = db.Column(db.JSON)                                  # ["2026-12-01", ...]
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (db.UniqueConstraint("sprint_id", "user_id", name="uq_mis_sprint_capacity"),)

    def to_dict(self):
        return {
            "id": self.id,
            "sprintId": self.sprint_id,
            "userId": self.user_id,
            "userName": self.user.username if self.user else None,
            "hoursPerDay": float(self.hours_per_day) if self.hours_per_day is not None else None,
            "daysOff": self.days_off or [],
        }


class MisSprintSnapshot(db.Model):
    """One row per sprint per day (daily job + on close) → burndown, velocity, CFD."""
    __tablename__ = "mis_sprint_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    sprint_id = db.Column(db.Integer, db.ForeignKey("mis_sprints.id", ondelete="CASCADE"), nullable=False, index=True)
    snap_date = db.Column(db.Date, nullable=False)
    remaining_hours = db.Column(db.Numeric(9, 2), nullable=False, default=0)
    committed_points = db.Column(db.Numeric(7, 1), nullable=False, default=0)
    done_points = db.Column(db.Numeric(7, 1), nullable=False, default=0)
    state_counts = db.Column(db.JSON)                              # {"To Do": 4, "In Progress": 2, ...}
    people = db.Column(db.JSON)          # {"<userId>": {"committed": pts, "done": pts}} — PBI/Bug owners (score)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    __table_args__ = (db.UniqueConstraint("sprint_id", "snap_date", name="uq_mis_sprint_snapshot_day"),)

    def to_dict(self):
        return {
            "sprintId": self.sprint_id,
            "date": _d(self.snap_date),
            "remainingHours": float(self.remaining_hours or 0),
            "committedPoints": float(self.committed_points or 0),
            "donePoints": float(self.done_points or 0),
            "stateCounts": self.state_counts or {},
        }


class MisRetroItem(db.Model):
    """Sprint retrospective card. An 'action' can be turned into a backlog work item."""
    __tablename__ = "mis_retro_items"

    id = db.Column(db.Integer, primary_key=True)
    sprint_id = db.Column(db.Integer, db.ForeignKey("mis_sprints.id", ondelete="CASCADE"), nullable=False, index=True)
    category = db.Column(db.String(12), nullable=False)           # went_well | improve | action
    text = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    work_item_id = db.Column(db.Integer, db.ForeignKey("mis_tasks.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())

    author = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "sprintId": self.sprint_id,
            "category": self.category,
            "text": self.text,
            "authorId": self.author_id,
            "authorName": self.author.username if self.author else None,
            "workItemId": self.work_item_id,
            "createdAt": _d(self.created_at),
        }


class MisSavedQuery(db.Model):
    """Saved work item query (filters + columns), private or shared in the project."""
    __tablename__ = "mis_saved_queries"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    filters = db.Column(db.JSON, nullable=False)
    columns = db.Column(db.JSON)
    is_shared = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    owner = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "ownerUserId": self.owner_user_id,
            "ownerName": self.owner.username if self.owner else None,
            "projectId": self.project_id,
            "name": self.name,
            "filters": self.filters or {},
            "columns": self.columns or [],
            "isShared": bool(self.is_shared),
            "createdAt": _d(self.created_at),
        }


class MisBoardConfig(db.Model):
    """Kanban settings per project (NULL = company) and backlog level (PBI / Feature / Epic):
    columns [{name, state, wip, split}] and swimlanes [name, ...]."""
    __tablename__ = "mis_board_configs"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
    level = db.Column(db.String(10), nullable=False)
    columns = db.Column(db.JSON, nullable=False)
    swimlanes = db.Column(db.JSON)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)
