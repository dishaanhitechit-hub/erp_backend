# app/models/grnMaster.py

from app.extensions import db
from datetime import datetime


class GrnMaster(db.Model):

    __tablename__ = "grn_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    grn_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    grn_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=True,
        index=True
    )

    grn_date = db.Column(
        db.Date,
        nullable=False
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "projects.project_code"
        ),
        nullable=False
    )

    received_category = db.Column(
        db.String(100),
        nullable=True
    )

    item_category = db.Column(
        db.String(100),
        nullable=True
    )

    cost_head = db.Column(
        db.String(100),
        nullable=True
    )

    order_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "order_master.id"
        ),
        nullable=True
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "vendors.id"
        ),
        nullable=True
    )

    billing_address = db.Column(
        db.Text,
        nullable=True
    )

    shipping_address = db.Column(
        db.Text,
        nullable=True
    )

    challan_no = db.Column(
        db.String(100),
        nullable=True
    )

    party_bill_no = db.Column(
        db.String(100),
        nullable=True
    )

    party_bill_date = db.Column(
        db.Date,
        nullable=True
    )

    deliver_vehicle_no = db.Column(
        db.String(100),
        nullable=True
    )

    delivered_concern = db.Column(
        db.String(200),
        nullable=True
    )

    unloading_datetime = db.Column(
        db.DateTime,
        nullable=True
    )

    physically_verified_by = db.Column(
        db.String(200),
        nullable=True
    )

    attached_doc = db.Column(
        db.Text,
        nullable=True
    )

    workflow_status = db.Column(
        db.String(30),
        default="Draft"
    )

    status = db.Column(
        db.String(30),
        default="Active"
    )

    created_by = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    rejected_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    updated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    submitted_at = db.Column(
        db.DateTime
    )

    final_approved_at = db.Column(
        db.DateTime
    )

    rejected_at = db.Column(
        db.DateTime
    )

    current_level = db.Column(
        db.Integer,
        default=0
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    pdf_url          = db.Column(db.Text,     nullable=True)
    pdf_token        = db.Column(db.Text,     nullable=True)
    pdf_generated_at = db.Column(db.DateTime, nullable=True)

    # ── relationships ──────────────────────────────────────────────
    project = db.relationship(
        "Project",
        backref="grns"
    )

    order = db.relationship(
        "OrderMaster",
        backref="grns"
    )

    vendor = db.relationship(
        "Vendor",
        backref="grns"
    )

    items = db.relationship(
        "GrnItem",
        backref="grn",
        cascade="all,delete-orphan"
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by]
    )

    submitter = db.relationship(
        "User",
        foreign_keys=[submitted_by]
    )

    approver = db.relationship(
        "User",
        foreign_keys=[approved_by]
    )

    rejector = db.relationship(
        "User",
        foreign_keys=[rejected_by]
    )

    updater = db.relationship(
        "User",
        foreign_keys=[updated_by]
    )


# app/models/grnMaster.py  (GrnItem — same file, same style as OrderItem)

class GrnItem(db.Model):

    __tablename__ = "grn_items"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    grn_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "grn_master.id"
        ),
        nullable=False
    )

    order_item_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "order_items.id"
        ),
        nullable=True
    )

    grnl = db.Column(
        db.String(50),
        nullable=True
    )

    item_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "items.item_code"
        ),
        nullable=True
    )

    note = db.Column(
        db.Text,
        nullable=True
    )

    unit = db.Column(
        db.String(30),
        nullable=True
    )

    order_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    pre_received_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    balance_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    current_received_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    use_location = db.Column(
        db.String(150),
        nullable=True
    )

    store_location = db.Column(
        db.String(150),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ── relationships ──────────────────────────────────────────────
    item = db.relationship(
        "Item"
    )

    order_item = db.relationship(
        "OrderItem"
    )
#