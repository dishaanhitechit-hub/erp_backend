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
        db.ForeignKey(
            "projects.project_code"
        ),
        nullable=False
    )

    # FK → category_master.fixed_code
    category_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "category_master.fixed_code"
        ),
        nullable=False
    )

    indent_date = db.Column(
        db.Date,
        nullable=False
    )

    priority = db.Column(
        db.String(30)
    )

    required_within = db.Column(
        db.Date
    )

    indent_placed_by = db.Column(
        db.String(150)
    )

    site_reg_serial_no = db.Column(
        db.String(150)
    )

    sale_order_no = db.Column(
        db.String(150)
    )

    remarks = db.Column(
        db.Text
    )

    # ==================================
    # BUSINESS STATUS
    # ==================================

    order_status = db.Column(
        db.String(30),
        default="Pending"
    )

    # ==================================
    # WORKFLOW STATUS
    # ==================================

    workflow_status = db.Column(
        db.String(30),
        default="Draft"
    )

    # Draft
    # Pending_L1
    # Pending_L2
    # Approved
    # Reback
    # Rejected

    current_level = db.Column(
        db.Integer,
        default=0
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    # ==================================
    # WORKFLOW DATES
    # ==================================

    submitted_at = db.Column(
        db.DateTime
    )

    final_approved_at = db.Column(
        db.DateTime
    )

    rejected_at = db.Column(
        db.DateTime
    )

    correction_sent_at = db.Column(
        db.DateTime
    )

    # ==================================
    # USER REFERENCES
    # ==================================

    created_by = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    approved_by = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    rejected_by = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )
    supporting_file = db.Column(
        db.Text
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

    creator = db.relationship(
        "User",
        foreign_keys=[created_by]
    )

    approver = db.relationship(
        "User",
        foreign_keys=[approved_by]
    )

    rejector = db.relationship(
        "User",
        foreign_keys=[rejected_by]
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

    # ==================================
    # STRING
    # ==================================

    def __repr__(self):

        return (
            f"<IndentMaster "
            f"{self.indent_no}>"
        )