# models/category_group.py
# SQLAlchemy ORM for Category & Group Master

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
    # Example:
    # Revenue
    # Direct Expenses
    # Fixed Asset

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
    )  # FK to users later

    def __repr__(self):
        return f"<GroupMaster {self.group_name}>"



# =========================================
# CATEGORY MASTER
# =========================================

class CategoryMaster(db.Model):
    __tablename__ = "category_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    category_name = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )
    # Example:
    # Items
    # Ledger
    # Unit
    # Tax

    head_under = db.Column(
        db.String(100),
        nullable=False
    )
    # Items / Ledger / Unit / Tax

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

    def __repr__(self):
        return f"<CategoryMaster {self.category_name}>"


