from app.extensions import db
from datetime import datetime


class DlrMaster(db.Model):

    __tablename__ = "dlr_master"

    id = db.Column(db.Integer, primary_key=True)

    dlr_no = db.Column(db.String(50), unique=True, nullable=False)

    dlr_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
    )

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order_master.id", ondelete="SET NULL"),
        nullable=True,
    )

    report_by = db.Column(db.String(200), nullable=True)
    verified_by = db.Column(db.String(200), nullable=True)
    scan_copy = db.Column(db.String(500), nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    current_level = db.Column(db.Integer, default=0)
    locked = db.Column(db.Boolean, default=False)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    final_approved_at = db.Column(db.DateTime, nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)

    # ── relationships ─────────────────────────────────────────────
    project = db.relationship("Project", backref="dlrs")
    vendor = db.relationship("Vendor", foreign_keys=[vendor_id], backref="dlrs")
    order = db.relationship("OrderMaster", foreign_keys=[order_id], backref="dlrs")

    items = db.relationship("DlrItem", backref="dlr", cascade="all,delete-orphan")

    creator = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
    updater = db.relationship("User", foreign_keys=[updated_by])


class DlrItem(db.Model):

    __tablename__ = "dlr_items"

    id = db.Column(db.Integer, primary_key=True)

    dlr_id = db.Column(
        db.Integer,
        db.ForeignKey("dlr_master.id", ondelete="CASCADE"),
        nullable=False,
    )

    sl_no = db.Column(db.Integer, nullable=False)

    man_id = db.Column(db.String(20), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(100), nullable=True)

    start_time = db.Column(db.String(10), nullable=True)
    finish_time = db.Column(db.String(10), nullable=True)
    lunch_hour = db.Column(db.Numeric(5, 2), default=0)
    working_hour = db.Column(db.Numeric(5, 2), default=0)
    bonus_hour = db.Column(db.Numeric(5, 2), default=0)
    total_working_hr = db.Column(db.Numeric(5, 2), default=0)

    job_location = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
