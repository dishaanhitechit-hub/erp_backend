from app.extensions import db
from datetime import datetime


class Unit(db.Model):
    __tablename__ = "units"

    # ==================================
    # PRIMARY KEY
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # BASIC DETAILS
    # ==================================

    unit_name = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    short_name = db.Column(
        db.String(50),
        nullable=False
    )

    unit_type = db.Column(
        db.String(50),
        nullable=False
    )
    # Parent / Child

    # ==================================
    # UNIT CATEGORY
    # ==================================

    category_name = db.Column(
        db.String(100),
        nullable=False
    )
    # Example:
    # Weight
    # Length
    # Count
    # Volume

    # ==================================
    # PARENT UNIT DETAILS
    # ==================================

    parent_unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=True
    )

    parent_unit_multiply_factor = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    # ==================================
    # SELF RELATIONSHIP
    # ==================================

    parent_unit = db.relationship(
        "Unit",
        remote_side=[id],
        backref="child_units",
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
        return f"<Unit {self.unit_name}>"