from app.extensions import db
from datetime import datetime


class PaymentVoucherMaster(db.Model):

    __tablename__ = "payment_voucher_master"

    id = db.Column(db.Integer, primary_key=True)

    payment_vouch_no   = db.Column(db.String(50), nullable=False)
    payment_vouch_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    payment_date = db.Column(db.Date, nullable=False)

    purchase_voucher_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase_voucher_master.id"),
        nullable=False,
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)

    payment_mode    = db.Column(db.String(10),  nullable=True)   # Cash / Bank
    cash_ac_id      = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)
    bank_ac_id      = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)
    utr_voucher_no  = db.Column(db.String(200), nullable=True)
    payment_remarks = db.Column(db.Text,        nullable=True)

    # Financials (amounts being paid in this voucher)
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
    project          = db.relationship("Project",              backref="payment_vouchers")
    purchase_voucher = db.relationship("PurchaseVoucherMaster", backref="payment_vouchers")
    vendor           = db.relationship("Vendor",               backref="payment_vouchers")
    cash_account     = db.relationship("BankCash", foreign_keys=[cash_ac_id])
    bank_account     = db.relationship("BankCash", foreign_keys=[bank_ac_id])

    items     = db.relationship("PaymentVoucherItem", backref="payment_voucher", cascade="all,delete-orphan")
    gst_lines = db.relationship("PaymentVoucherGst",  backref="payment_voucher", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class PaymentVoucherItem(db.Model):
    """BASIC section — one row per purchase-voucher item being paid."""

    __tablename__ = "payment_voucher_items"

    id                 = db.Column(db.Integer, primary_key=True)
    payment_voucher_id = db.Column(db.Integer, db.ForeignKey("payment_voucher_master.id"), nullable=False)

    # Reference to the originating purchase voucher item (for paid-amount tracking)
    pv_item_id = db.Column(db.Integer, db.ForeignKey("purchase_voucher_items.id"), nullable=True)

    sl_no          = db.Column(db.Integer,      nullable=False)
    cc_code_id     = db.Column(db.Integer,      db.ForeignKey("cc_codes.id"), nullable=True)
    cc_code        = db.Column(db.String(50),   nullable=True)
    cc_name        = db.Column(db.String(200),  nullable=True)
    booked_amount  = db.Column(db.Numeric(14, 2), default=0)   # snapshot from purchase voucher
    current_amount = db.Column(db.Numeric(14, 2), default=0)   # amount being paid now

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cc_code_rel = db.relationship("CCCode")
    pv_item     = db.relationship("PurchaseVoucherItem")


class PaymentVoucherGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per payment voucher."""

    __tablename__ = "payment_voucher_gst"

    id                 = db.Column(db.Integer, primary_key=True)
    payment_voucher_id = db.Column(db.Integer, db.ForeignKey("payment_voucher_master.id"), nullable=False)

    gst_type       = db.Column(db.String(10),    nullable=False)   # IGST / CGST / SGST
    cc_code        = db.Column(db.String(50),    nullable=True)
    cc_name        = db.Column(db.String(200),   nullable=True)
    booked_amount  = db.Column(db.Numeric(14, 2), default=0)       # snapshot
    current_amount = db.Column(db.Numeric(14, 2), default=0)       # being paid now
    is_selected    = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
