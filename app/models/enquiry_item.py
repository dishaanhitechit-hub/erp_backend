# =========================================================
# app/models/enquiry_item.py
# =========================================================

from app.extensions import db
from datetime import datetime


class EnquiryItem(db.Model):

    __tablename__ = "enquiry_item"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # =====================================================
    # FOREIGN KEYS
    # =====================================================

    enquiry_id = db.Column(
        db.Integer,
        db.ForeignKey("enquiry_master.id"),
        nullable=False
    )

    indent_item_id = db.Column(
        db.Integer,
        db.ForeignKey("indent_items.id"),
        nullable=False
    )

    item_code = db.Column(
        db.String(50),
        db.ForeignKey("items.item_code"),
        nullable=False
    )

    # =====================================================
    # QTY DETAILS
    # =====================================================

    indent_qty = db.Column(
        db.Numeric(18, 2),
        nullable=False
    )

    enquiry_qty = db.Column(
        db.Numeric(18, 2),
        nullable=False
    )

    # =====================================================
    # EXTRA DETAILS
    # =====================================================

    location = db.Column(
        db.String(255)
    )

    note = db.Column(
        db.Text
    )

    status = db.Column(
        db.String(20),
        default="Active"
    )

    # =====================================================
    # AUDIT FIELDS
    # =====================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime
    )

    created_by = db.Column(
        db.Integer
    )

    updated_by = db.Column(
        db.Integer
    )

    # =====================================================
    # RELATIONSHIPS
    # =====================================================

    item = db.relationship(
        "Item",
        backref="enquiry_items",
        lazy=True
    )

    indent_item = db.relationship(
        "IndentItem",
        backref="enquiry_items",
        lazy=True
    )