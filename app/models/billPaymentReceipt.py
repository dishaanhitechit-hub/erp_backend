from app.extensions import db
from datetime import datetime


class BillPaymentReceiptMaster(db.Model):

    __tablename__ = "bill_payment_receipt_master"

    id           = db.Column(db.Integer, primary_key=True)
    receipt_no   = db.Column(db.String(50), nullable=False)
    receipt_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    payment_date = db.Column(db.Date, nullable=False)

    purchase_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase_bill_master.id"),
        nullable=False,
    )

    # Snapshots auto-populated from the linked purchase bill
    bvs_date         = db.Column(db.Date,        nullable=True)
    vendor_bill_no   = db.Column(db.String(100), nullable=True)
    vendor_bill_date = db.Column(db.Date,        nullable=True)
    order_no         = db.Column(db.String(100), nullable=True)

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

    # Financials (amounts being paid in this receipt)
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
    project       = db.relationship("Project",          backref="bill_payment_receipts")
    purchase_bill = db.relationship("PurchaseBillMaster", backref="bill_payment_receipts")
    vendor        = db.relationship("Vendor",            backref="bill_payment_receipts")
    cash_account  = db.relationship("BankCash", foreign_keys=[cash_ac_id])
    bank_account  = db.relationship("BankCash", foreign_keys=[bank_ac_id])

    items     = db.relationship("BillPaymentReceiptItem", backref="receipt", cascade="all,delete-orphan")
    gst_lines = db.relationship("BillPaymentReceiptGst",  backref="receipt", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class BillPaymentReceiptItem(db.Model):
    """BASIC section — one row per purchase-bill item being paid."""

    __tablename__ = "bill_payment_receipt_items"

    id         = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("bill_payment_receipt_master.id"), nullable=False)

    # Reference to originating purchase bill item (for paid-amount tracking)
    pb_item_id = db.Column(db.Integer, db.ForeignKey("purchase_bill_items.id"), nullable=True)

    sl_no          = db.Column(db.Integer,      nullable=False)
    cc_code        = db.Column(db.String(50),   nullable=True)
    cc_name        = db.Column(db.String(200),  nullable=True)
    booked_amount  = db.Column(db.Numeric(14, 2), default=0)   # snapshot from purchase bill
    current_amount = db.Column(db.Numeric(14, 2), default=0)   # being paid now

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    pb_item = db.relationship("PurchaseBillItem")


class BillPaymentReceiptGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per receipt."""

    __tablename__ = "bill_payment_receipt_gst"

    id         = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("bill_payment_receipt_master.id"), nullable=False)

    gst_type       = db.Column(db.String(10),    nullable=False)   # IGST / CGST / SGST
    cc_code        = db.Column(db.String(50),    nullable=True)
    cc_name        = db.Column(db.String(200),   nullable=True)
    booked_amount  = db.Column(db.Numeric(14, 2), default=0)       # snapshot
    current_amount = db.Column(db.Numeric(14, 2), default=0)       # being paid now
    is_selected    = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
