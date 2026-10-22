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
        nullable=True
    )

    is_asset = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    asset_code = db.Column(
        db.String(50),
        db.ForeignKey("assets.asset_code"),
        nullable=True
    )

    # ==================================
    # ITEM DETAILS
    # ==================================

    note = db.Column(
        db.Text,
        nullable=True
    )

    qty = db.Column(
        db.Numeric(17, 4),
        nullable=False
    )

    location = db.Column(
        db.String(1500),
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

    asset = db.relationship(
        "Asset",
        backref="indent_items",
        lazy=True,
        foreign_keys=[asset_code],
        primaryjoin="IndentItem.asset_code == Asset.asset_code"
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
        db.ForeignKey("users.id"),
        nullable=True
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by],
        lazy=True
    )

    # ==================================
    # STRING
    # ==================================

    def __repr__(self):
        return f"<IndentItem {self.item_code}>"