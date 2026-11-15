# app/models/misTask.py
# MIS — Self Task + shared activity log (also used later by follow-ups).
import uuid as _uuid

from app.extensions import db

TASK_STATUSES = ("To Do", "In Progress", "On Hold", "Done", "Cancelled")
OPEN_STATUSES = ("To Do", "In Progress", "On Hold")
TASK_PRIORITIES = ("Low", "Medium", "High", "Critical")


def _d(v):
    return v.isoformat() if v else None


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
    due_date = db.Column(db.Date, index=True)
    completed_at = db.Column(db.DateTime)

    estimated_hours = db.Column(db.Numeric(7, 2))
    actual_hours = db.Column(db.Numeric(7, 2))
    reopen_count = db.Column(db.Integer, nullable=False, default=0)   # feeds performance "error" score

    tags = db.Column(db.JSON)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    owner = db.relationship("User", foreign_keys=[owner_user_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    project = db.relationship("Project")

    def is_overdue(self, today):
        return bool(self.due_date and self.status in OPEN_STATUSES and self.due_date < today)

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
            "dueDate": _d(self.due_date),
            "completedAt": _d(self.completed_at),
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
    created_at = db.Column(db.DateTime, server_default=db.func.now())

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
