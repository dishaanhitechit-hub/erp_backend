# app/models/ginMaster.py

from app.extensions import db
from datetime import datetime


class GinMaster(db.Model):

    __tablename__ = "gin_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    gin_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    gin_date = db.Column(
        db.Date,
        nullable=False
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    issue_category = db.Column(
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

    cost_factor = db.Column(
        db.String(100),
        nullable=True
    )

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order_master.id"),
        nullable=True
    )

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    site = db.Column(
        db.String(200),
        nullable=True
    )

    despatch_from = db.Column(
        db.String(200),
        nullable=True
    )

    shipping_to = db.Column(
        db.Text,
        nullable=True
    )

    recommendation_by = db.Column(
        db.String(200),
        nullable=True
    )

    issue_slip_no = db.Column(
        db.String(100),
        nullable=True
    )

    handed_over_to = db.Column(
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

    current_level = db.Column(
        db.Integer,
        default=0
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
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

    submitted_at = db.Column(db.DateTime)
    final_approved_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # ── relationships ──────────────────────────────────────────────
    project = db.relationship("Project", backref="gins")
    order = db.relationship("OrderMaster", backref="gins")
    vendor = db.relationship("Vendor", backref="gins")

    items = db.relationship(
        "GinItem",
        backref="gin",
        cascade="all,delete-orphan"
    )

    creator = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])
    updater = db.relationship("User", foreign_keys=[updated_by])


class GinItem(db.Model):

    __tablename__ = "gin_items"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    gin_id = db.Column(
        db.Integer,
        db.ForeignKey("gin_master.id"),
        nullable=False
    )

    order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("order_items.id"),
        nullable=True
    )

    ginl = db.Column(
        db.String(50),
        nullable=True
    )

    issue_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    stock_location = db.Column(
        db.String(150),
        nullable=True
    )

    item_used_location = db.Column(
        db.String(150),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ── relationships ──────────────────────────────────────────────
    order_item = db.relationship("OrderItem")
