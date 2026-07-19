# app/models/brrMaster.py
# BRR — Bill Received Register

from app.extensions import db
from datetime import datetime


class BrrMaster(db.Model):

    __tablename__ = "brr_master"

    id = db.Column(db.Integer, primary_key=True)

    brr_no   = db.Column(db.String(50), unique=True, nullable=False)
    brr_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    order_category = db.Column(db.String(100), nullable=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order_master.id"),
        nullable=True
    )

    # Party bill details
    party_bill_no = db.Column(db.String(100), nullable=True)
    party_date    = db.Column(db.Date,        nullable=True)

    # Receipt details
    received_category  = db.Column(db.String(200), nullable=True)
    submitted_by_name  = db.Column(db.String(200), nullable=True)
    submission_date    = db.Column(db.Date,        nullable=True)
    received_through   = db.Column(db.String(200), nullable=True)
    received_reference = db.Column(db.String(200), nullable=True)

    # Financials
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    # Attachment
    attached_doc = db.Column(db.String(500), nullable=True)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by       = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at       = db.Column(db.DateTime)
    final_approved_at  = db.Column(db.DateTime)
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project = db.relationship("Project", backref="brr_list")
    vendor  = db.relationship("Vendor",  backref="brr_list")
    order   = db.relationship("OrderMaster", backref="brr_list")

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
