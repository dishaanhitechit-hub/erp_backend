from app.extensions import db
from datetime import datetime


class CreditNoteMaster(db.Model):
    __tablename__ = "credit_note_master"

    id               = db.Column(db.Integer, primary_key=True)
    credit_note_no   = db.Column(db.String(50), nullable=False)
    credit_note_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    entry_date   = db.Column(db.Date, nullable=False)
    project_code = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)

    bill_number  = db.Column(db.String(200), nullable=True)
    bill_date    = db.Column(db.Date,        nullable=True)
    order_number = db.Column(db.String(200), nullable=True)
    order_date   = db.Column(db.Date,        nullable=True)

    vendor_name = db.Column(db.String(300), nullable=True)
    vendor_gstn = db.Column(db.String(50),  nullable=True)

    debit_note_no   = db.Column(db.String(200), nullable=True)
    debit_note_date = db.Column(db.Date,        nullable=True)

    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    remarks = db.Column(db.Text, nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

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

    project   = db.relationship("Project",       backref="credit_notes")
    items     = db.relationship("CreditNoteItem", backref="credit_note", cascade="all,delete-orphan")
    gst_lines = db.relationship("CreditNoteGst",  backref="credit_note", cascade="all,delete-orphan")
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class CreditNoteItem(db.Model):
    __tablename__ = "credit_note_items"

    id             = db.Column(db.Integer, primary_key=True)
    credit_note_id = db.Column(db.Integer, db.ForeignKey("credit_note_master.id"), nullable=False)

    sl_no        = db.Column(db.Integer,        nullable=False)
    cc_code      = db.Column(db.String(50),     nullable=True)
    cc_name      = db.Column(db.String(200),    nullable=True)
    description  = db.Column(db.Text,           nullable=True)
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_percent  = db.Column(db.Numeric(5, 2),  default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CreditNoteGst(db.Model):
    __tablename__ = "credit_note_gst"

    id             = db.Column(db.Integer, primary_key=True)
    credit_note_id = db.Column(db.Integer, db.ForeignKey("credit_note_master.id"), nullable=False)

    gst_type    = db.Column(db.String(10),    nullable=False)   # IGST / CGST / SGST
    cc_code     = db.Column(db.String(50),    nullable=True)
    cc_name     = db.Column(db.String(200),   nullable=True)
    percent     = db.Column(db.Numeric(5, 2),  default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)
    is_selected = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
