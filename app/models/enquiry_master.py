# =========================================================
# app/models/enquiry_master.py
# =========================================================

from app.extensions import db
from datetime import datetime


class EnquiryMaster(db.Model):

    __tablename__ = "enquiry_master"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    enquiry_no = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    enquiry_date = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # =====================================================
    # FOREIGN KEYS
    # =====================================================

    indent_id = db.Column(
        db.Integer,
        db.ForeignKey("indent_master.id"),
        nullable=False
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    category_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "category_master.fixed_code"
        ),
        nullable=False
    )

    # =====================================================
    # BASIC DETAILS
    # =====================================================

    enquiry_to = db.Column(
        db.String(255)
    )

    address = db.Column(
        db.Text
    )

    quotation_url = db.Column(
        db.Text
    )

    enquiry_status = db.Column(
        db.String(30),
        default="Draft"
    )

    status = db.Column(
        db.String(20),
        default="Active"
    )

    # =====================================================
    # AUDIT FIELDS
    # =====================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime
    )

    created_by = db.Column(
        db.Integer
    )

    updated_by = db.Column(
        db.Integer
    )

    # =====================================================
    # RELATIONSHIPS
    # =====================================================

    enquiry_items = db.relationship(
        "EnquiryItem",
        backref="enquiry_master",
        lazy=True,
        cascade="all, delete-orphan"
    )

    enquiry_terms = db.relationship(
        "EnquiryTerm",
        backref="enquiry_master",
        lazy=True,
        cascade="all, delete-orphan"
    )

    indent = db.relationship(
        "IndentMaster",
        backref="enquiries",
        lazy=True
    )

    project = db.relationship(
        "Project",
        backref="enquiries",
        lazy=True
    )

    category = db.relationship(
        "CategoryMaster",
        backref="enquiries",
        lazy=True
    )