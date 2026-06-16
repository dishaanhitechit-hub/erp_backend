# app/models/bssMaster.py
# BSS — Vendor Billing by SRN

from app.extensions import db
from datetime import datetime


class BssMaster(db.Model):

    __tablename__ = "bss_master"

    id = db.Column(db.Integer, primary_key=True)

    bss_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    bss_date = db.Column(db.Date, nullable=False)

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

    received_category = db.Column(db.String(100), nullable=True)
    item_category     = db.Column(db.String(100), nullable=True)
    cost_head         = db.Column(db.String(100), nullable=True)

    party_bill_no = db.Column(db.String(100), nullable=True)
    party_date    = db.Column(db.Date,        nullable=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=True
    )

    site             = db.Column(db.String(200), nullable=True)
    billing_address  = db.Column(db.Text,        nullable=True)
    shipping_address = db.Column(db.Text,        nullable=True)

    # financials — computed on create/edit
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

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
    project = db.relationship("Project",                  backref="bss_list")
    vendor  = db.relationship("Vendor",                   backref="bss_list")
    order   = db.relationship("ProjectWorkOrderMaster",   backref="bss_list")

    items = db.relationship(
        "BssItem",
        backref="bss",
        cascade="all,delete-orphan"
    )

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])


class BssItem(db.Model):

    __tablename__ = "bss_items"

    id = db.Column(db.Integer, primary_key=True)

    bss_id = db.Column(
        db.Integer,
        db.ForeignKey("bss_master.id"),
        nullable=False
    )

    srn_item_id = db.Column(
        db.Integer,
        db.ForeignKey("srn_items.id"),
        nullable=False
    )

    billing_qty = db.Column(db.Numeric(12, 2), default=0)
    rate        = db.Column(db.Numeric(12, 2), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    srn_item = db.relationship("SrnItem")
