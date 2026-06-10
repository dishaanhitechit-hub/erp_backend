from app.extensions import db
from datetime import datetime


class ConcreteRegistry(db.Model):
    __tablename__ = 'concrete_registry'

    id = db.Column(db.Integer, primary_key=True)

    projectcode = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    reference_order_no = db.Column(db.String(50), nullable=False)
    project_sub_location = db.Column(db.String(50), nullable=False)
    segment = db.Column(db.String(50), nullable=False)

    pouring_date = db.Column(db.Date, nullable=False)
    pouring_start_date = db.Column(db.Time, nullable=False)
    pouring_end_date = db.Column(db.Time, nullable=False)

    grade_concrete = db.Column(db.String(50), nullable=False)
    concrete_volume = db.Column(db.String(50), nullable=False)

    requisition_no = db.Column(db.String(50), nullable=False)
    requisition_by = db.Column(db.String(50), nullable=False)

    vehicle_number = db.Column(db.String(50), nullable=False)
    batch_no = db.Column(db.String(50), nullable=False)

    attach_batch_file = db.Column(db.String(255), nullable=True)

    # ── Workflow ───────────────────────────────────────────────────
    workflow_status = db.Column(
        db.String(30),
        default="Draft"
    )

    status = db.Column(
        db.String(30),
        default="Active"
    )

    current_level = db.Column(
        db.Integer,
        default=0
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    # ── Audit ──────────────────────────────────────────────────────
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    rejected_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    updated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    submitted_at = db.Column(db.DateTime)
    final_approved_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    project = db.relationship(
        "Project",
        backref="concrete_registry"
    )

    creator = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
