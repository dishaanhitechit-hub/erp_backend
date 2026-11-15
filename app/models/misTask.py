# app/models/misTask.py
# MIS — Self Task + shared activity log (also used later by follow-ups).
import os
import uuid as _uuid
from datetime import datetime, time as _time, timezone
from zoneinfo import ZoneInfo

from app.extensions import db

TASK_STATUSES = ("To Do", "In Progress", "On Hold", "Done", "Cancelled")
OPEN_STATUSES = ("To Do", "In Progress", "On Hold")
TASK_PRIORITIES = ("Low", "Medium", "High", "Critical")
REOPEN_STATUSES = ("Pending", "Approved", "Rejected")

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

    priority = db.Column(db.String(20), nullable=False, default="Medium")
    status = db.Column(db.String(20), nullable=False, default="To Do", index=True)

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

    # all timestamps are UTC (set in Python so the DB server's time zone does not matter)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_user_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    project = db.relationship("Project")

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
