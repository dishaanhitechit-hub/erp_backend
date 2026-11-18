# app/models/logisticsBill.py
# Logistics Bill Register — freight/transporter bill management

from app.extensions import db
from datetime import datetime


class LogisticsBill(db.Model):

    __tablename__ = "logistics_bills"

    id = db.Column(db.Integer, primary_key=True)

    lb_no = db.Column(db.String(50), unique=True, nullable=False)
    lb_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    bill_date = db.Column(db.Date, nullable=False)
    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Transporter/vendor — from Vendor Master (vendors table)
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=False
    )

    vendor_invoice_no = db.Column(db.String(100), nullable=True)
    vendor_invoice_date = db.Column(db.Date, nullable=True)

    # Fixed | Per_KM | Per_Ton | Per_Trip
    freight_basis = db.Column(db.String(20), nullable=True)

    # ── charges ───────────────────────────────────────────────────
    basic_freight = db.Column(db.Numeric(17, 2), default=0)
    loading_charges = db.Column(db.Numeric(17, 2), default=0)
    unloading_charges = db.Column(db.Numeric(17, 2), default=0)
    waiting_charges = db.Column(db.Numeric(17, 2), default=0)
    toll_charges = db.Column(db.Numeric(17, 2), default=0)
    other_charges_description = db.Column(db.String(200), nullable=True)
    other_charges = db.Column(db.Numeric(17, 2), default=0)

    taxable_amount = db.Column(db.Numeric(17, 2), default=0)

    # ── tax ───────────────────────────────────────────────────────
    gst_type = db.Column(db.String(20), default="IGST")  # IGST | CGST_SGST

    igst_percent = db.Column(db.Numeric(5, 2), default=0)
    igst_amount = db.Column(db.Numeric(17, 2), default=0)
    cgst_percent = db.Column(db.Numeric(5, 2), default=0)
    cgst_amount = db.Column(db.Numeric(17, 2), default=0)
    sgst_percent = db.Column(db.Numeric(5, 2), default=0)
    sgst_amount = db.Column(db.Numeric(17, 2), default=0)

    tds_percent = db.Column(db.Numeric(5, 2), default=0)
    tds_amount = db.Column(db.Numeric(17, 2), default=0)

    total_amount = db.Column(db.Numeric(17, 2), default=0)
    net_payable = db.Column(db.Numeric(17, 2), default=0)

    # ── payment ───────────────────────────────────────────────────
    payment_status = db.Column(db.String(30), default="Unpaid")  # Unpaid | Partial | Paid

    # Finance link — set when LB is posted to AP (approval).
    # Non-null ⇒ journal exists; deletion requires reversing the voucher first.
    voucher_id = db.Column(db.Integer, nullable=True)

    remarks = db.Column(db.Text, nullable=True)
    attached_doc = db.Column(db.Text, nullable=True)

    # ── workflow ──────────────────────────────────────────────────
    workflow_status = db.Column(db.String(30), default="Draft")
    status = db.Column(db.String(30), default="Active")
    current_level = db.Column(db.Integer, default=0)
    locked = db.Column(db.Boolean, default=False)

    # ── audit ─────────────────────────────────────────────────────
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    final_approved_at = db.Column(db.DateTime, nullable=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    correction_sent_at = db.Column(db.DateTime, nullable=True)

    # ── relationships ─────────────────────────────────────────────
    project = db.relationship("Project", foreign_keys=[project_code], backref="logistics_bills")
    vendor = db.relationship("Vendor", backref="logistics_bills")

    challans = db.relationship(
        "LogisticsBillChallan",
        backref="logistics_bill",
        cascade="all,delete-orphan",
        order_by="LogisticsBillChallan.id",
    )

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])


class LogisticsBillChallan(db.Model):

    __tablename__ = "logistics_bill_challans"

    id = db.Column(db.Integer, primary_key=True)

    lb_id = db.Column(
        db.Integer,
        db.ForeignKey("logistics_bills.id"),
        nullable=False
    )

    dc_id = db.Column(
        db.Integer,
        db.ForeignKey("dc_master.id"),
        nullable=False
    )

    billing_remarks = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── relationships ─────────────────────────────────────────────
    dc = db.relationship("DcMaster", backref="bill_challans")
