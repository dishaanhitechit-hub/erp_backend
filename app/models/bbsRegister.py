from app.extensions import db
from datetime import datetime


class BbsRegister(db.Model):

    __tablename__ = "bbs_register"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)

    # ── Identity ───────────────────────────────────────────────────
    bbs_no = db.Column(db.String(50), unique=True, nullable=False)

    bbs_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    # ── Project ────────────────────────────────────────────────────
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # ── BBS Details ────────────────────────────────────────────────
    revision = db.Column(db.String(50), nullable=True)

    bbs_title = db.Column(db.String(500), nullable=True)

    # ── Location Details ───────────────────────────────────────────
    reference_order_no = db.Column(db.String(100), nullable=True)

    project_sub_location = db.Column(db.String(200), nullable=True)

    segment_layer = db.Column(db.String(200), nullable=True)

    # ── Received Details ───────────────────────────────────────────
    received_date = db.Column(db.Date, nullable=True)

    received_time = db.Column(db.Time, nullable=True)

    received_by = db.Column(db.String(200), nullable=True)

    delivered_by = db.Column(db.String(200), nullable=True)

    delivery_mode = db.Column(db.String(100), nullable=True)
    # e.g. By Hand / By Letter / By Mail / WhatsApp / By Data Card

    delivery_reference = db.Column(db.String(200), nullable=True)

    # ── Attachment ─────────────────────────────────────────────────
    attachment = db.Column(db.Text, nullable=True)

    # ── Workflow ───────────────────────────────────────────────────
    workflow_status = db.Column(db.String(30), default="Draft")

    status = db.Column(db.String(30), default="Active")

    current_level = db.Column(db.Integer, default=0)

    locked = db.Column(db.Boolean, default=False)

    # ── Audit ──────────────────────────────────────────────────────
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at = db.Column(db.DateTime)

    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    final_approved_at = db.Column(db.DateTime)

    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    rejected_at = db.Column(db.DateTime)

    correction_sent_at = db.Column(db.DateTime)

    # ── Relationships ──────────────────────────────────────────────
    project = db.relationship("Project", backref="bbs_registers")

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
