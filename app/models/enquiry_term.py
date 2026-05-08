# =========================================================
# app/models/enquiry_term.py
# =========================================================

from app.extensions import db
from datetime import datetime


class EnquiryTerm(db.Model):

    __tablename__ = "enquiry_term"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # =====================================================
    # FOREIGN KEY
    # =====================================================

    enquiry_id = db.Column(
        db.Integer,
        db.ForeignKey("enquiry_master.id"),
        nullable=False
    )

    # =====================================================
    # TERM DETAILS
    # =====================================================

    header = db.Column(
        db.String(255)
    )

    description = db.Column(
        db.Text
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