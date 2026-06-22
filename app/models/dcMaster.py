# app/models/dcMaster.py
# DC — Delivery Challan

from app.extensions import db
from datetime import datetime


class DcMaster(db.Model):

    __tablename__ = "dc_master"

    id = db.Column(db.Integer, primary_key=True)

    dc_no = db.Column(db.String(50), unique=True, nullable=False)
    challan_date = db.Column(db.Date, nullable=False)

    # Purchase_Order | Site_Transfer_Order
    order_type = db.Column(db.String(50), nullable=False)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order_master.id"),
        nullable=False
    )

    # From side — vendor (Purchase_Order) or project (Site_Transfer_Order)
    from_vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    from_project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=True
    )

    shipping_from_address = db.Column(db.Text, nullable=True)

    # To side — always current project
    to_project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    shipping_to_address = db.Column(db.Text, nullable=True)

    contact_person = db.Column(db.String(200), nullable=True)
    purpose_for_delivery = db.Column(db.String(200), nullable=True)
    delivery_mode = db.Column(db.String(100), nullable=True)
    vehicle_number = db.Column(db.String(100), nullable=True)
    driver_name = db.Column(db.String(150), nullable=True)
    driver_contact_number = db.Column(db.String(20), nullable=True)

    eway_bill_number = db.Column(db.String(100), nullable=True)
    eway_bill_date = db.Column(db.Date, nullable=True)
    eway_bill_expiry_date = db.Column(db.Date, nullable=True)

    attached_doc = db.Column(db.Text, nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    status = db.Column(db.String(30), default="Active")
    current_level = db.Column(db.Integer, default=0)
    locked = db.Column(db.Boolean, default=False)

    # audit
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at = db.Column(db.DateTime)
    final_approved_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # relationships
    order = db.relationship("OrderMaster", backref="dc_list")
    from_vendor = db.relationship("Vendor", backref="dc_list")

    from_project = db.relationship(
        "Project",
        foreign_keys="[DcMaster.from_project_code]",
        backref="dc_from_list"
    )

    to_project = db.relationship(
        "Project",
        foreign_keys="[DcMaster.to_project_code]",
        backref="dc_to_list"
    )

    items = db.relationship(
        "DcItem",
        backref="dc",
        cascade="all,delete-orphan"
    )

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])


class DcItem(db.Model):

    __tablename__ = "dc_items"

    id = db.Column(db.Integer, primary_key=True)

    dc_id = db.Column(
        db.Integer,
        db.ForeignKey("dc_master.id"),
        nullable=False
    )

    order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("order_items.id"),
        nullable=False
    )

    item_code = db.Column(
        db.String(50),
        db.ForeignKey("items.item_code"),
        nullable=True
    )

    issue_qty = db.Column(db.Numeric(12, 2), default=0)
    stock_location = db.Column(db.String(150), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    order_item = db.relationship("OrderItem")
    item = db.relationship("Item")
