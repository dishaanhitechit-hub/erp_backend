# app/models/indent_item.py

from app.extensions import db
from datetime import datetime


class IndentItem(db.Model):
    __tablename__ = "indent_items"

    # ==================================
    # PRIMARY KEY
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # FK REFERENCES
    # ==================================

    indent_id = db.Column(
        db.Integer,
        db.ForeignKey("indent_master.id"),
        nullable=False
    )

    item_code = db.Column(
        db.String(50),
        db.ForeignKey("items.item_code"),
        nullable=False
    )

    # ==================================
    # ITEM DETAILS
    # ==================================

    note = db.Column(
        db.Text,
        nullable=True
    )

    qty = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )

    location = db.Column(
        db.String(150),
        nullable=True
    )

    # ==================================
    # RELATIONSHIPS
    # ==================================

    item = db.relationship(
        "Item",
        backref="indent_items",
        lazy=True
    )

    # ==================================
    # STATUS
    # ==================================

    item_status = db.Column(
        db.String(30),
        default="Pending"
    )

    # ==================================
    # AUDIT
    # ==================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    created_by = db.Column(
        db.Integer,
        nullable=True
    )

    # ==================================
    # STRING
    # ==================================

    def __repr__(self):
        return f"<IndentItem {self.item_code}>"