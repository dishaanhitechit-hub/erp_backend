# app/models/ORDER_projectwork.py
#
# Project-Work Order ORM
# ──────────────────────
# Three models live in this file (mirrors the OrderMaster family):
#
#   ProjectWorkOrderMaster       →  pw_order_master
#   ProjectWorkOrderItem         →  pw_order_items
#   ProjectWorkOrderTermsCondition →  pw_order_terms_conditions
#
# Key difference from OrderMaster:
#   • NO indent / indent-item linkage
#   • Items are sourced directly from the item-list (items.item_code)
# ──────────────────────────────────────────────────────────────────

from app.extensions import db
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════
# 1.  PROJECT-WORK ORDER MASTER
# ═══════════════════════════════════════════════════════════════════

class ProjectWorkOrderMaster(db.Model):

    __tablename__ = "pw_order_master"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ── Order Identity ─────────────────────────────────────────────
    order_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    # ── Project & Category ─────────────────────────────────────────
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Stores a JSON list of selected sub-category codes, e.g. '["SVC","COMP"]'
    # Multiple categories are allowed so this is Text with no FK constraint.
    sub_codes = db.Column(
        db.Text,
        nullable=True
    )

    category_code = db.Column(
        db.String(50),
        nullable=True
    )

    # ── Vendor ────────────────────────────────────────────────────
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    # ── Financials ────────────────────────────────────────────────
    booked_amount = db.Column(
        db.Numeric(14, 4),
        nullable=False,
        default=0
    )

    basic_amount = db.Column(
        db.Numeric(14, 2),
        default=0
    )

    gst_amount = db.Column(
        db.Numeric(14, 2),
        default=0
    )

    total_amount = db.Column(
        db.Numeric(14, 2),
        default=0
    )

    # ── Dates ─────────────────────────────────────────────────────
    order_date = db.Column(
        db.Date,
        nullable=False
    )

    quotation_no = db.Column(
        db.String(60),
        nullable=False,
        default="1"
    )

    quotation_date = db.Column(
        db.Date
    )

    validity_date = db.Column(
        db.Date
    )

    # ── Addresses & Notes ─────────────────────────────────────────
    billing_address = db.Column(
        db.Text
    )

    shipping_address = db.Column(
        db.Text
    )

    order_message = db.Column(
        db.Text
    )

    supporting_file = db.Column(
        db.Text
    )

    # ── Workflow ──────────────────────────────────────────────────
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

    # ── Audit – Created ───────────────────────────────────────────
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ── Audit – Updated ───────────────────────────────────────────
    updated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # ── Audit – Submitted ─────────────────────────────────────────
    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    submitted_at = db.Column(
        db.DateTime
    )

    # ── Audit – Approved ──────────────────────────────────────────
    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    final_approved_at = db.Column(
        db.DateTime
    )

    # ── Audit – Rejected ──────────────────────────────────────────
    rejected_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    rejected_at = db.Column(
        db.DateTime
    )

    correction_sent_at = db.Column(
        db.DateTime
    )

    # ── Relationships ─────────────────────────────────────────────
    project = db.relationship(
        "Project",
        backref="pw_orders"
    )

    vendor = db.relationship(
        "Vendor",
        backref="pw_orders"
    )

    items = db.relationship(
        "ProjectWorkOrderItem",
        backref="order",
        cascade="all,delete-orphan"
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by]
    )

    updater = db.relationship(
        "User",
        foreign_keys=[updated_by]
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


# ═══════════════════════════════════════════════════════════════════
# 2.  PROJECT-WORK ORDER ITEM
#     Items come directly from the item-list.
#     No indent / indent-item linkage.
# ═══════════════════════════════════════════════════════════════════

class ProjectWorkOrderItem(db.Model):

    __tablename__ = "pw_order_items"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ── Parent Order ──────────────────────────────────────────────
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=False
    )

    # ── Item Reference (directly from item list) ──────────────────
    item_code = db.Column(
        db.String(50),
        db.ForeignKey("items.item_code"),
        nullable=False
    )

    # ── Item Details ──────────────────────────────────────────────
    custom_note = db.Column(
        db.Text
    )

    qty = db.Column(
        db.Numeric(12, 2)
    )

    amend_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    used_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    balance_qty = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    rate = db.Column(
        db.Numeric(12, 2)
    )

    amount = db.Column(
        db.Numeric(14, 2)
    )

    gst_percent = db.Column(
        db.Numeric(5, 2)
    )

    gst_amount = db.Column(
        db.Numeric(14, 2)
    )

    location = db.Column(
        db.String(150)
    )

    item_status = db.Column(
        db.String(30),
        default="Pending"
    )

    # ── Audit ─────────────────────────────────────────────────────
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ── Relationships ─────────────────────────────────────────────
    item = db.relationship(
        "Item"
    )


# ═══════════════════════════════════════════════════════════════════
# 3.  PROJECT-WORK ORDER TERMS & CONDITIONS
#     Identical in behaviour to OrderTermsCondition.
# ═══════════════════════════════════════════════════════════════════

class ProjectWorkOrderTermsCondition(db.Model):

    __tablename__ = "pw_order_terms_conditions"

    # ── Primary Key ────────────────────────────────────────────────
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ── Parent Order ──────────────────────────────────────────────
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("pw_order_master.id"),
        nullable=False
    )

    # ── Term Reference ────────────────────────────────────────────
    term_id = db.Column(
        db.Integer,
        db.ForeignKey("term_conditions.id"),
        nullable=False
    )

    # ── Optional User-edited Description ─────────────────────────
    custom_description = db.Column(
        db.Text
    )

    sequence_no = db.Column(
        db.Integer,
        default=1
    )

    status = db.Column(
        db.String(30),
        default="Active"
    )

    # ── Audit ─────────────────────────────────────────────────────
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ── Relationships ─────────────────────────────────────────────
    order = db.relationship(
        "ProjectWorkOrderMaster",
        backref=db.backref(
            "terms_conditions",
            cascade="all,delete-orphan"
        )
    )

    term = db.relationship(
        "TermConditions",
        lazy=True
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by]
    )
