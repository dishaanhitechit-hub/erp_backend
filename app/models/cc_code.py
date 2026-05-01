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