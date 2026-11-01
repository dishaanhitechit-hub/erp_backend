# models/category_group.py

from app.extensions import db
from datetime import datetime


# =========================================
# GROUP MASTER
# =========================================

class GroupMaster(db.Model):
    __tablename__ = "group_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    group_name = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    head_under = db.Column(
        db.String(100),
        nullable=False
    )
    # Profit & Loss / Balance Sheet

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

    def __repr__(self):
        return f"<GroupMaster {self.group_name}>"


# =========================================
# CATEGORY MASTER
# Centralized Business Category Registry
# =========================================

class CategoryMaster(db.Model):
    __tablename__ = "category_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    fixed_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )
    # Example:
    # RAW_MATERIAL
    # FIXED_ASSET
    # ELECTRICAL_VENDOR

    category_name = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

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

    def __repr__(self):
        return f"<CategoryMaster {self.category_name}>"

# =========================================
# SUB GROUP MASTER
# One Group can have many Sub Groups.
# Each Sub Group belongs to one Group.
# Category is chosen on the CC code, not here.
# =========================================

class SubGroupMaster(db.Model):
    __tablename__ = "sub_group_master"
    __table_args__ = (
        db.UniqueConstraint("group_id", "sub_group_name", name="uq_sub_group_group_name"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Stable code used by logic/filters, e.g. FIXED_ASSET, PROJECT_OH
    fixed_code = db.Column(db.String(50), unique=True, nullable=False)

    sub_group_name = db.Column(db.String(150), nullable=False)

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("group_master.id"),
        nullable=False
    )

    status = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)

    group = db.relationship("GroupMaster", backref="sub_groups", lazy=True)

    def __repr__(self):
        return f"<SubGroupMaster {self.sub_group_name}>"
