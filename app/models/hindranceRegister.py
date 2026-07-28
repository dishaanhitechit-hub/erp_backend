from app.extensions import db
from datetime import datetime


class HindranceRegister(db.Model):

    __tablename__ = "hindrance_register"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)

    # ── Identity ───────────────────────────────────────────────────
    hindrance_no = db.Column(db.String(50), unique=True, nullable=False)

    hindrance_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    # ── Project ────────────────────────────────────────────────────
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # ── Header ─────────────────────────────────────────────────────
    hindrance_date = db.Column(db.Date, nullable=True)

    # ── Hindrance Details ──────────────────────────────────────────
    title_of_hindrance = db.Column(db.String(500), nullable=True)

    cause_of_hindrance = db.Column(db.Text, nullable=True)

    # ── Effected Resources ─────────────────────────────────────────
    manpower_details = db.Column(db.Text, nullable=True)

    manpower_amount = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    plant_machinery_details = db.Column(db.Text, nullable=True)

    plant_machinery_amount = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    materials_details = db.Column(db.Text, nullable=True)

    materials_amount = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    total_effected_amount = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    # ── Attachment ─────────────────────────────────────────────────
    attachment = db.Column(db.Text, nullable=True)

    # ── Intimation ─────────────────────────────────────────────────
    intimation_to = db.Column(db.String(200), nullable=True)

    intimation_via = db.Column(db.String(100), nullable=True)

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
    project = db.relationship("Project", backref="hindrance_registers")

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
