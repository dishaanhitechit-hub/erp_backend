from app.extensions import db
from datetime import datetime


class Item(db.Model):
    __tablename__ = "items"

    # ==================================
    # PRIMARY KEY
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # ITEM BASIC DETAILS
    # ==================================

    item_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    # FK → category_master.fixed_code
    category_code = db.Column(
        db.String(50),
        db.ForeignKey("category_master.fixed_code"),
        nullable=False
    )

    # FK → cc_codes.id
    cc_code_id = db.Column(
        db.Integer,
        db.ForeignKey("cc_codes.id"),
        nullable=False
    )

    item_name = db.Column(
        db.String(200),
        nullable=False
    )

    item_description = db.Column(
        db.Text,
        nullable=True
    )

    # ==================================
    # UNIT + TAX DETAILS
    # ==================================

    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=True
    )

    hsn_sac = db.Column(
        db.String(50),
        nullable=True
    )

    gst_percentage = db.Column(
        db.Numeric(5, 2),
        nullable=True
    )

    # ==================================
    # RELATIONSHIPS
    # ==================================

    category = db.relationship(
        "CategoryMaster",
        backref="items",
        lazy=True
    )

    cc_code = db.relationship(
        "CCCode",
        backref="items",
        lazy=True
    )

    unit = db.relationship(
        "Unit",
        backref="items",
        lazy=True
    )

    # ==================================
    # STATUS + AUDIT
    # ==================================

    status = db.Column(
        db.String(30),
        default="Active"
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

    created_by = db.Column(
        db.Integer,
        nullable=True
    )

    # ==================================
    # STRING REPRESENTATION
    # ==================================

    def __repr__(self):
        return f"<Item {self.item_code} - {self.item_name}>"