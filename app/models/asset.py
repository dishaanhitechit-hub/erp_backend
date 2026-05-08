# models/asset.py
# SQLAlchemy ORM for Asset Master
# Similar to Item Master

from app.extensions import db
from datetime import datetime


class Asset(db.Model):
    __tablename__ = "assets"

    # ==================================
    # PRIMARY KEY
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # ASSET BASIC DETAILS
    # ==================================

    asset_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )  # Auto Generated

    # asset category fetched from category_master
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("category_master.id"),
        nullable=False
    )

    # cc name fetched from cc_codes table
    cc_code_id = db.Column(
        db.Integer,
        db.ForeignKey("cc_codes.id"),
        nullable=False
    )

    asset_name = db.Column(
        db.String(200),
        nullable=False
    )

    asset_description = db.Column(
        db.Text,
        nullable=True
    )

    # ==================================
    # ASSET DETAILS
    # ==================================

    unit = db.Column(
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

    purchase_value = db.Column(
        db.Numeric(15, 2),
        nullable=True
    )

    depreciation_percentage = db.Column(
        db.Numeric(5, 2),
        nullable=True
    )

    useful_life_years = db.Column(
        db.Integer,
        nullable=True
    )

    # ==================================
    # RELATIONSHIPS
    # ==================================

    category_code = db.Column(
        db.String(50),
        db.ForeignKey("category_master.fixed_code"),
        nullable=False
    )

    cc_code = db.relationship(
        "CCCode",
        backref="assets",
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
    )  # FK to users later

    # ==================================
    # STRING REPRESENTATION
    # ==================================

    def __repr__(self):
        return f"<Asset {self.asset_code} - {self.asset_name}>"