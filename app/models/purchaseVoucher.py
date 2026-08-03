from app.extensions import db
from datetime import datetime


class PurchaseVoucherMaster(db.Model):

    __tablename__ = "purchase_voucher_master"

    id = db.Column(db.Integer, primary_key=True)

    voucher_no   = db.Column(db.String(50), nullable=False)
    voucher_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    processing_date    = db.Column(db.Date, nullable=False)
    voucher_date       = db.Column(db.Date, nullable=True)
    vendor_voucher_no  = db.Column(db.String(100), nullable=True)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)

    remarks = db.Column(db.Text, nullable=True)

    # Financials
    basic_amount         = db.Column(db.Numeric(14, 2), default=0)
    gst_amount           = db.Column(db.Numeric(14, 2), default=0)
    discount             = db.Column(db.Numeric(14, 2), default=0)
    round_off            = db.Column(db.Numeric(10, 2), default=0)
    total_invoice_amount = db.Column(db.Numeric(14, 2), default=0)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

    # Audit
    created_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at       = db.Column(db.DateTime)
    approved_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at  = db.Column(db.DateTime)
    rejected_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project   = db.relationship("Project", backref="purchase_vouchers")
    vendor    = db.relationship("Vendor",  backref="purchase_vouchers")

    items     = db.relationship("PurchaseVoucherItem", backref="voucher", cascade="all,delete-orphan")
    gst_lines = db.relationship("PurchaseVoucherGst",  backref="voucher", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class PurchaseVoucherItem(db.Model):
    """BASIC section — one row per CC Code entry."""

    __tablename__ = "purchase_voucher_items"

    id         = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("purchase_voucher_master.id"), nullable=False)

    sl_no        = db.Column(db.Integer, nullable=False)
    cc_code_id   = db.Column(db.Integer, db.ForeignKey("cc_codes.id"), nullable=True)
    description  = db.Column(db.Text,           nullable=True)
    basic_amount = db.Column(db.Numeric(14, 2), default=0)

    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    cc_code_rel = db.relationship("CCCode")


class PurchaseVoucherGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per voucher."""

    __tablename__ = "purchase_voucher_gst"

    id         = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("purchase_voucher_master.id"), nullable=False)

    gst_type    = db.Column(db.String(10),    nullable=False)  # IGST / CGST / SGST
    cc_code     = db.Column(db.String(50),    nullable=True)
    cc_name     = db.Column(db.String(200),   nullable=True)
    description = db.Column(db.Text,          nullable=True)
    percent     = db.Column(db.Numeric(5, 2),  default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)
    is_selected = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
