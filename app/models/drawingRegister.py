# app/models/drawingRegister.py

from app.extensions import db
from datetime import datetime


class DrawingRegister(db.Model):

    __tablename__ = "drawing_register"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    dr_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # ── Drawing Details ────────────────────────────────────────────
    drawing_no = db.Column(
        db.String(100),
        nullable=True
    )

    revision = db.Column(
        db.String(50),
        nullable=True
    )

    drawing_title = db.Column(
        db.String(500),
        nullable=True
    )

    # ── Location Details ───────────────────────────────────────────
    reference_order_no = db.Column(
        db.String(100),
        nullable=True
        # NOTE: plain text for now — sale order lookup to be wired later
    )

    project_sub_location = db.Column(
        db.String(200),
        nullable=True
    )

    segment_layer = db.Column(
        db.String(200),
        nullable=True
    )

    # ── Received Details ───────────────────────────────────────────
    received_date = db.Column(
        db.Date,
        nullable=True
    )

    received_time = db.Column(
        db.Time,
        nullable=True
    )

    received_by = db.Column(
        db.String(200),
        nullable=True
    )

    delivered_by = db.Column(
        db.String(200),
        nullable=True
    )

    delivery_mode = db.Column(
        db.String(100),
        nullable=True
        # e.g. By Hand / By Letter / By Mail / WhatsApp / By Data Card
    )

    delivery_reference = db.Column(
        db.String(200),
        nullable=True
    )

    attachment = db.Column(
        db.Text,
        nullable=True
    )

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

    # ── Relationships ──────────────────────────────────────────────
    project = db.relationship("Project", backref="drawing_registers")

    creator = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
