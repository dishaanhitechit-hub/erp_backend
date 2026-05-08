# app/models/indent_master.py

from app.extensions import db
from datetime import datetime


class IndentMaster(db.Model):
    __tablename__ = "indent_master"

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

    indent_no = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    # FK → projects.project_code
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # FK → category_master.fixed_code
    category_code = db.Column(
        db.String(50),
        db.ForeignKey("category_master.fixed_code"),
        nullable=False
    )

    indent_date = db.Column(
        db.Date,
        nullable=False
    )

    priority = db.Column(
        db.String(30),
        nullable=True
    )

    required_within = db.Column(
        db.Date,
        nullable=True
    )

    indent_placed_by = db.Column(
        db.String(150),
        nullable=True
    )

    site_reg_serial_no = db.Column(
        db.String(150),
        nullable=True
    )

    sale_order_no = db.Column(
        db.String(150),
        nullable=True
    )

    remarks = db.Column(
        db.Text,
        nullable=True
    )

    # ==================================
    # STATUS
    # ==================================

    indent_status = db.Column(
        db.String(30),
        default="Draft"
    )
    # Draft
    # Submitted
    # Approved
    # Rejected

    order_status = db.Column(
        db.String(30),
        default="Pending"
    )

    # ==================================
    # RELATIONSHIPS
    # ==================================

    project = db.relationship(
        "Project",
        backref="indents",
        lazy=True
    )

    category = db.relationship(
        "CategoryMaster",
        backref="indents",
        lazy=True
    )

    indent_items = db.relationship(
        "IndentItem",
        backref="indent",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==================================
    # AUDIT
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
    # STRING
    # ==================================

    def __repr__(self):
        return f"<IndentMaster {self.indent_no}>"