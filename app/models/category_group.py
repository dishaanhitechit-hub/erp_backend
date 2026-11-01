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
# Tree under a Group:
#   Group -> Sub Group (level 0) -> Sub Group 1 (level 1) -> Sub Group 2 (level 2)
# Deeper levels are optional. Category is chosen on the CC code, not here.
# =========================================

SUB_GROUP_MAX_LEVELS = 3  # Sub Group, Sub Group 1, Sub Group 2


class SubGroupMaster(db.Model):
    __tablename__ = "sub_group_master"
    __table_args__ = (
        # same name allowed under different parents, not twice under one parent
        db.UniqueConstraint("group_id", "parent_id", "sub_group_name", name="uq_sub_group_parent_name"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Unique code, always UPPERCASE (typed by user or auto generated)
    fixed_code = db.Column(db.String(50), unique=True, nullable=False)

    sub_group_name = db.Column(db.String(150), nullable=False)

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("group_master.id"),
        nullable=False
    )

    # Empty for top level Sub Group; set for Sub Group 1 / Sub Group 2
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("sub_group_master.id"),
        nullable=True
    )

    # 0 = Sub Group, 1 = Sub Group 1, 2 = Sub Group 2
    level = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    status = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)

    group = db.relationship("GroupMaster", backref="sub_groups", lazy=True)
    parent = db.relationship("SubGroupMaster", remote_side=[id], backref="children", lazy=True)

    def path(self):
        """List of nodes from top Sub Group down to this one."""
        nodes, node = [], self
        while node is not None:
            nodes.append(node)
            node = node.parent
        return nodes[::-1]

    def __repr__(self):
        return f"<SubGroupMaster {self.sub_group_name}>"
