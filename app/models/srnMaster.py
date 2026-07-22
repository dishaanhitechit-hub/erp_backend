# app/models/srnMaster.py

from app.extensions import db
from datetime import datetime


class SrnMaster(db.Model):

    __tablename__ = "srn_master"

    id = db.Column(db.Integer, primary_key=True)

    srn_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    srn_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=True,
        index=True
    )

    srn_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    received_category = db.Column(db.String(100), nullable=True)
    item_category     = db.Column(db.String(100), nullable=True)
    cost_head         = db.Column(db.String(100), nullable=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=True
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    billing_address  = db.Column(db.Text,        nullable=True)
    shipping_address = db.Column(db.Text,        nullable=True)
    challan_no       = db.Column(db.String(100), nullable=True)
    party_bill_no    = db.Column(db.String(100), nullable=True)
    party_bill_date  = db.Column(db.Date,        nullable=True)

    deliver_vehicle_no    = db.Column(db.String(100), nullable=True)
    delivered_concern     = db.Column(db.String(200), nullable=True)
    unloading_datetime    = db.Column(db.DateTime,    nullable=True)
    physically_verified_by = db.Column(db.String(200), nullable=True)

    attached_doc = db.Column(db.Text, nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

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

    # ── relationships ──────────────────────────────────────────────
    project = db.relationship("Project",              backref="srns")
    order   = db.relationship("ProjectWorkOrderMaster", backref="srns")
    vendor  = db.relationship("Vendor",               backref="srns")

    items = db.relationship(
        "SrnItem",
        backref="srn",
        cascade="all,delete-orphan"
    )

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])


class SrnItem(db.Model):

    __tablename__ = "srn_items"

    id = db.Column(db.Integer, primary_key=True)

    srn_id = db.Column(
        db.Integer,
        db.ForeignKey("srn_master.id"),
        nullable=False
    )

    pw_order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_items.id"),
        nullable=True
    )

    srnl = db.Column(db.String(50), nullable=True)

    current_received_qty = db.Column(db.Numeric(12, 2), default=0)
    use_location         = db.Column(db.String(150),    nullable=True)
    store_location       = db.Column(db.String(150),    nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── relationships ──────────────────────────────────────────────
    pw_order_item = db.relationship("ProjectWorkOrderItem")
