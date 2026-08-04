from app.extensions import db
from datetime import datetime


class ContraEntryMaster(db.Model):

    __tablename__ = "contra_entry_master"

    id = db.Column(db.Integer, primary_key=True)

    voucher_no   = db.Column(db.String(50), nullable=False)
    contra_uuid  = db.Column(db.String(36), unique=True, nullable=True, index=True)

    entry_date   = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    remarks      = db.Column(db.Text, nullable=True)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

    # Audit
    created_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at       = db.Column(db.DateTime)
    approved_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at  = db.Column(db.DateTime)
    rejected_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project = db.relationship("Project", backref="contra_entries")
    lines   = db.relationship("ContraEntryLine", backref="entry", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class ContraEntryLine(db.Model):

    __tablename__ = "contra_entry_lines"

    id        = db.Column(db.Integer, primary_key=True)
    contra_id = db.Column(db.Integer, db.ForeignKey("contra_entry_master.id"), nullable=False)

    sl_no      = db.Column(db.Integer,    nullable=False)
    dr_cr      = db.Column(db.String(3),  nullable=False)   # Dr / Cr

    account_id = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=False)

    opening_balance  = db.Column(db.Numeric(14, 2), default=0)
    debit_amount     = db.Column(db.Numeric(14, 2), default=0)
    credit_amount    = db.Column(db.Numeric(14, 2), default=0)
    closing_balance  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship("BankCash", foreign_keys=[account_id])
