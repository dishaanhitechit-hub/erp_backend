# app/models/misFollowup.py
# MIS — Follow-up board (Scrum-style): Sprints → Agendas → relay Steps.
#
#   Supervisor creates an Agenda and assigns Step 1. The assignee completes it
#   and hands off to the next person (Step 2) … or returns it to the supervisor
#   for Review. The supervisor closes it, or rejects it (a rework step).
#   Only one step is active (Pending / In Progress) at a time.
import uuid as _uuid
from datetime import datetime, date

from app.extensions import db
from app.models.misTask import _d

SPRINT_TYPES = ("Weekly", "Monthly")
SPRINT_STATUSES = ("Planned", "Active", "Closed")

BOARD_STATUSES = ("Backlog", "To Do", "In Progress", "Review", "Done")
FU_PRIORITIES = ("Low", "Medium", "High", "Critical")

STEP_ACTIVE = ("Pending", "In Progress")
STEP_STATUSES = ("Pending", "In Progress", "Done", "Rejected", "Reassigned", "Cancelled")


def _uuid4():
    return str(_uuid.uuid4())


class MisSprint(db.Model):
    __tablename__ = "mis_sprints"

    id = db.Column(db.Integer, primary_key=True)
    sprint_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True, default=_uuid4)
    sprint_code = db.Column(db.String(30), unique=True)            # SPR-2026-00001

    name = db.Column(db.String(120), nullable=False)
    sprint_type = db.Column(db.String(10), nullable=False, default="Weekly")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    goal = db.Column(db.Text)
    status = db.Column(db.String(10), nullable=False, default="Planned", index=True)

    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)  # NULL = company
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    closed_at = db.Column(db.DateTime)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    project = db.relationship("Project")
    creator = db.relationship("User")

    def to_dict(self, counts=None):
        out = {
            "id": self.id,
            "uuid": self.sprint_uuid,
            "sprintCode": self.sprint_code,
            "name": self.name,
            "sprintType": self.sprint_type,
            "startDate": _d(self.start_date),
            "endDate": _d(self.end_date),
            "goal": self.goal,
            "status": self.status,
            "projectId": self.project_id,
            "projectCode": self.project.project_code if self.project else None,
            "projectName": self.project.project_name if self.project else None,
            "createdBy": self.created_by,
            "createdByName": self.creator.username if self.creator else None,
            "closedAt": _d(self.closed_at),
            "isCurrent": bool(self.start_date and self.end_date and self.start_date <= date.today() <= self.end_date),
            "createdAt": _d(self.created_at),
        }
        if counts is not None:
            out.update(counts)
        return out


class MisFollowup(db.Model):
    """An agenda / story on the follow-up board."""
    __tablename__ = "mis_followups"

    id = db.Column(db.Integer, primary_key=True)
    fu_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True, default=_uuid4)
    fu_code = db.Column(db.String(30), unique=True)                # FU-2026-00001

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    board_status = db.Column(db.String(20), nullable=False, default="To Do", index=True)
    story_points = db.Column(db.Integer)
    due_date = db.Column(db.Date, index=True)

    sprint_id = db.Column(db.Integer, db.ForeignKey("mis_sprints.id"), nullable=True, index=True)  # NULL = backlog
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
    supervisor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    closed_at = db.Column(db.DateTime)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.now(), onupdate=datetime.utcnow)

    sprint = db.relationship("MisSprint", backref="followups")
    project = db.relationship("Project")
    supervisor = db.relationship("User", foreign_keys=[supervisor_user_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    steps = db.relationship("MisFollowupStep", backref="followup", order_by="MisFollowupStep.seq_no",
                            cascade="all, delete-orphan")

    @property
    def active_step(self):
        for s in reversed(self.steps):
            if s.status in STEP_ACTIVE:
                return s
        return None

    def is_overdue(self, today=None):
        today = today or date.today()
        return bool(self.due_date and self.board_status != "Done" and self.due_date < today)

    def to_dict(self, with_steps=False):
        cur = self.active_step
        done_steps = sum(1 for s in self.steps if s.status == "Done")
        out = {
            "id": self.id,
            "uuid": self.fu_uuid,
            "fuCode": self.fu_code,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "boardStatus": self.board_status,
            "storyPoints": self.story_points,
            "dueDate": _d(self.due_date),
            "isOverdue": self.is_overdue(),
            "sprintId": self.sprint_id,
            "sprintName": self.sprint.name if self.sprint else None,
            "projectId": self.project_id,
            "projectCode": self.project.project_code if self.project else None,
            "projectName": self.project.project_name if self.project else None,
            "supervisorUserId": self.supervisor_user_id,
            "supervisorName": self.supervisor.username if self.supervisor else None,
            "createdBy": self.created_by,
            "currentStep": cur.to_dict() if cur else None,
            "stepCount": len(self.steps),
            "doneSteps": done_steps,
            "reworkCount": sum(1 for s in self.steps if s.is_rework),
            "closedAt": _d(self.closed_at),
            "createdAt": _d(self.created_at),
            "updatedAt": _d(self.updated_at),
        }
        if with_steps:
            out["steps"] = [s.to_dict() for s in self.steps]
        return out


class MisFollowupStep(db.Model):
    """One hand-off in the relay chain."""
    __tablename__ = "mis_followup_steps"

    id = db.Column(db.Integer, primary_key=True)
    followup_id = db.Column(db.Integer, db.ForeignKey("mis_followups.id", ondelete="CASCADE"), nullable=False, index=True)
    seq_no = db.Column(db.Integer, nullable=False)
    assignee_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    instruction = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="Pending", index=True)
    is_rework = db.Column(db.Boolean, nullable=False, default=False)   # supervisor sent it back → quality score

    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)          # pick-up speed = started_at − assigned_at
    due_date = db.Column(db.Date)
    completed_at = db.Column(db.DateTime)
    completion_note = db.Column(db.Text)

    assignee = db.relationship("User", foreign_keys=[assignee_user_id])
    assigner = db.relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (
        db.UniqueConstraint("followup_id", "seq_no", name="uq_mis_followup_step_seq"),
    )

    @property
    def on_time(self):
        if not self.due_date or not self.completed_at:
            return None
        return self.completed_at.date() <= self.due_date

    def to_dict(self):
        return {
            "id": self.id,
            "seqNo": self.seq_no,
            "assigneeUserId": self.assignee_user_id,
            "assigneeName": self.assignee.username if self.assignee else None,
            "assigneeEmpCode": self.assignee.emp_code if self.assignee else None,
            "assignedBy": self.assigned_by,
            "assignedByName": self.assigner.username if self.assigner else None,
            "instruction": self.instruction,
            "status": self.status,
            "isRework": bool(self.is_rework),
            "assignedAt": _d(self.assigned_at),
            "startedAt": _d(self.started_at),
            "dueDate": _d(self.due_date),
            "completedAt": _d(self.completed_at),
            "completionNote": self.completion_note,
            "onTime": self.on_time,
        }
