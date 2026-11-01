# models/cc_code.py
# SQLAlchemy ORM for CC Code Master
# Group + Category come from existing GroupMaster and CategoryMaster tables
from app.extensions import db
from datetime import datetime


class CCCode(db.Model):
    __tablename__ = "cc_codes"

    # =====================================
    # PRIMARY KEY
    # =====================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    cc_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )  # Auto Generated / Unique

    cc_name = db.Column(
        db.String(200),
        nullable=False
    )

    # =====================================
    # FOREIGN KEY FROM EXISTING TABLES
    # =====================================

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("group_master.id"),
        nullable=False
    )

    category_code = db.Column(
        db.String(50),
        db.ForeignKey("category_master.fixed_code"),
        nullable=False
    )

    # Optional sub group (must belong to group_id)
    sub_group_id = db.Column(
        db.Integer,
        db.ForeignKey("sub_group_master.id"),
        nullable=True
    )

    # =====================================
    # RELATIONSHIPS
    # =====================================

    group = db.relationship(
        "GroupMaster",
        backref="cc_codes",
        lazy=True
    )

    category = db.relationship(
        "CategoryMaster",
        backref="cc_codes",
        lazy=True
    )

    sub_group = db.relationship(
        "SubGroupMaster",
        backref="cc_codes",
        lazy=True
    )

    # Denormalised from GroupMaster.head_under for join-free filtering.
    # "Profit & Loss" | "Balance Sheet" | None (legacy rows)
    head_under = db.Column(db.String(100), nullable=True)

    # Only meaningful when head_under == "Balance Sheet".
    # True  → Non-Ledger  (will NOT be used for ledger connection)
    # False → Ledger Head (WILL be used for ledger connection)
    # None  → P&L group or not yet set
    is_non_ledger = db.Column(db.Boolean, nullable=True)

    # =====================================
    # STATUS + AUDIT
    # =====================================

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
    )  # FK to users table later

    # =====================================
    # STRING REPRESENTATION
    # =====================================

    def __repr__(self):
        return f"<CCCode {self.cc_code} - {self.cc_name}>"