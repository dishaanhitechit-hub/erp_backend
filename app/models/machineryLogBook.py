# app/models/machineryLogBook.py
# Machinery Log Book (master) + Log Book Entry

from app.extensions import db
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════
# 1. MACHINERY LOG BOOK MASTER
# ═══════════════════════════════════════════════════════════════════

class MachineryLogBook(db.Model):

    __tablename__ = "machinery_log_book"

    id = db.Column(db.Integer, primary_key=True)

    log_book_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    create_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Party Order → pw_order_master
    party_order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=True
    )

    machinery_name   = db.Column(db.String(200), nullable=True)
    machinery_reg_no = db.Column(db.String(100), nullable=True)

    fuel_consumption_unit     = db.Column(db.String(50),  nullable=True)
    fuel_consumption_per_unit = db.Column(db.Numeric(10, 2), nullable=True)

    # workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

    # audit
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by   = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at       = db.Column(db.DateTime)
    final_approved_at  = db.Column(db.DateTime)
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # relationships
    project     = db.relationship("Project",                backref="log_books")
    party_order = db.relationship("ProjectWorkOrderMaster", backref="log_books")

    entries = db.relationship(
        "LogBookEntry",
        backref="log_book",
        cascade="all,delete-orphan"
    )

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])


# ═══════════════════════════════════════════════════════════════════
# 2. LOG BOOK ENTRY
# ═══════════════════════════════════════════════════════════════════

class LogBookEntry(db.Model):

    __tablename__ = "log_book_entries"

    id = db.Column(db.Integer, primary_key=True)

    log_uid = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    log_book_id = db.Column(
        db.Integer,
        db.ForeignKey("machinery_log_book.id"),
        nullable=False
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Running Details
    running_date        = db.Column(db.Date,     nullable=True)
    running_start_time  = db.Column(db.Time,     nullable=True)
    running_finish_time = db.Column(db.Time,     nullable=True)

    # Job Location
    project_sub_location = db.Column(db.String(200), nullable=True)
    segment_layer        = db.Column(db.String(200), nullable=True)

    # Handling Record
    work_monitoring_by = db.Column(db.String(200), nullable=True)
    operator_name      = db.Column(db.String(200), nullable=True)

    # workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

    # audit
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by   = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at       = db.Column(db.DateTime)
    final_approved_at  = db.Column(db.DateTime)
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # relationships
    project   = db.relationship("Project", backref="log_entries")

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
