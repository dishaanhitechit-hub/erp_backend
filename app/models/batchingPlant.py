from app.extensions import db
from datetime import datetime


class BatchingPlantMaster(db.Model):

    __tablename__ = "batching_plant_master"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(db.Integer, primary_key=True)

    # ── Identity ───────────────────────────────────────────────────
    despatch_no = db.Column(db.String(50), unique=True, nullable=False)

    bp_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    # ── Project ────────────────────────────────────────────────────
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    production_date = db.Column(db.Date, nullable=True)

    # ── Order / Vendor link ────────────────────────────────────────
    pw_order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=True
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    # ── Materials Details ──────────────────────────────────────────
    material_type = db.Column(db.String(100), nullable=True)

    grade = db.Column(db.String(100), nullable=True)

    unit_of_concrete = db.Column(db.String(50), nullable=True)

    volume_of_concrete = db.Column(db.Numeric(12, 2), nullable=True)

    weight_of_concrete = db.Column(db.Numeric(12, 2), nullable=True)

    # ── Production Details ─────────────────────────────────────────
    production_unit_name = db.Column(db.String(100), nullable=True)

    operator_name = db.Column(db.String(100), nullable=True)

    production_completed = db.Column(db.String(100), nullable=True)

    batch_slip_no = db.Column(db.String(50), nullable=True)

    # ── Transit Details ────────────────────────────────────────────
    vehicle_number = db.Column(db.String(50), nullable=True)

    driver_name = db.Column(db.String(100), nullable=True)

    loading_finish_time = db.Column(db.String(50), nullable=True)

    pouring_start_time = db.Column(db.String(50), nullable=True)

    completion_time = db.Column(db.String(50), nullable=True)

    # ── Requirement Details ────────────────────────────────────────
    requisition_by = db.Column(db.String(100), nullable=True)

    requisition_date = db.Column(db.Date, nullable=True)

    requisition_time = db.Column(db.String(50), nullable=True)

    # ── Workflow ───────────────────────────────────────────────────
    workflow_status = db.Column(db.String(30), default="Draft")

    status = db.Column(db.String(30), default="Active")

    current_level = db.Column(db.Integer, default=0)

    locked = db.Column(db.Boolean, default=False)

    # ── Audit – Created ───────────────────────────────────────────
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── Audit – Updated ───────────────────────────────────────────
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # ── Audit – Submitted ─────────────────────────────────────────
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at = db.Column(db.DateTime)

    # ── Audit – Approved ──────────────────────────────────────────
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    final_approved_at = db.Column(db.DateTime)

    # ── Audit – Rejected ──────────────────────────────────────────
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    rejected_at = db.Column(db.DateTime)

    correction_sent_at = db.Column(db.DateTime)

    # ── Relationships ──────────────────────────────────────────────
    project = db.relationship("Project", backref="batching_plants")

    pw_order = db.relationship("ProjectWorkOrderMaster", backref="batching_plants")

    vendor = db.relationship("Vendor", backref="batching_plants")

    creator = db.relationship("User", foreign_keys=[created_by])

    updater = db.relationship("User", foreign_keys=[updated_by])

    submitter = db.relationship("User", foreign_keys=[submitted_by])

    approver = db.relationship("User", foreign_keys=[approved_by])

    rejector = db.relationship("User", foreign_keys=[rejected_by])
