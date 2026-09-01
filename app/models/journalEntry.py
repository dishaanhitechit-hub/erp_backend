from app.extensions import db
from datetime import datetime


class JournalEntryMaster(db.Model):

    __tablename__ = "journal_entry_master"

    id            = db.Column(db.Integer, primary_key=True)

    voucher_no    = db.Column(db.String(50), nullable=False)
    journal_uuid  = db.Column(db.String(36), unique=True, nullable=True, index=True)

    entry_date    = db.Column(db.Date, nullable=False)

    project_code  = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    remarks       = db.Column(db.Text, nullable=True)
    total_debit   = db.Column(db.Numeric(14, 2), default=0)
    total_credit  = db.Column(db.Numeric(14, 2), default=0)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

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
    project = db.relationship("Project", backref="journal_entries")
    lines   = db.relationship("JournalEntryLine", backref="entry", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class JournalEntryLine(db.Model):

    __tablename__ = "journal_entry_lines"

    id         = db.Column(db.Integer, primary_key=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal_entry_master.id"), nullable=False)

    sl_no        = db.Column(db.Integer,    nullable=False)
    account_type = db.Column(db.String(20), nullable=True)   # CC / Vendor — derived from cc_id / vendor_id
    dr_cr        = db.Column(db.String(3),  nullable=False)  # Dr / Cr

    cc_id     = db.Column(db.Integer, db.ForeignKey("cc_codes.id"), nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"),  nullable=True)

    opening_balance = db.Column(db.Numeric(14, 2), default=0)
    debit_amount    = db.Column(db.Numeric(14, 2), default=0)
    credit_amount   = db.Column(db.Numeric(14, 2), default=0)
    closing_balance = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cc     = db.relationship("CCCode", foreign_keys=[cc_id])
    vendor = db.relationship("Vendor", foreign_keys=[vendor_id])
