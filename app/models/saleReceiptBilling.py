from app.extensions import db
from datetime import datetime


class SaleReceiptBillingMaster(db.Model):
    """Child billing record — one per certified bill, holds workflow + items."""

    __tablename__ = "sale_receipt_billing"

    id       = db.Column(db.Integer, primary_key=True)
    srb_no   = db.Column(db.String(50), nullable=False)
    srb_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    receipt_id = db.Column(
        db.Integer,
        db.ForeignKey("sale_receipt_master.id"),
        nullable=False,
    )

    og_sale_order_no = db.Column(db.String(50), nullable=True)
    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=True,
    )
    sale_order_date = db.Column(db.Date, nullable=True)

    certified_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id"),
        nullable=True,
    )
    certified_bill_no = db.Column(db.String(50), nullable=True)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    invoice_no   = db.Column(db.String(200), nullable=True)
    invoice_date = db.Column(db.Date, nullable=True)

    bill_to_address = db.Column(db.Text, nullable=True)
    ship_to_address = db.Column(db.Text, nullable=True)

    bill_abstract_no   = db.Column(db.String(200), nullable=True)
    bill_abstract_date = db.Column(db.Date, nullable=True)

    basic_amount         = db.Column(db.Numeric(14, 2), default=0)
    gst_amount           = db.Column(db.Numeric(14, 2), default=0)
    discount             = db.Column(db.Numeric(14, 2), default=0)
    round_off            = db.Column(db.Numeric(10, 2), default=0)
    total_invoice_amount = db.Column(db.Numeric(14, 2), default=0)

    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

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

    project        = db.relationship("Project",           backref="sale_receipt_billings")
    og_so          = db.relationship("OgSaleOrderMaster", backref="sale_receipt_billings")
    certified_bill = db.relationship("BillingMaster",     backref="sale_receipt_billings")
    items          = db.relationship("SaleReceiptItem",   backref="billing", cascade="all,delete-orphan")
    gst_lines      = db.relationship("SaleReceiptGst",    backref="billing", cascade="all,delete-orphan")
    creator        = db.relationship("User", foreign_keys=[created_by])
    updater        = db.relationship("User", foreign_keys=[updated_by])
    submitter      = db.relationship("User", foreign_keys=[submitted_by])
    approver       = db.relationship("User", foreign_keys=[approved_by])
    rejector       = db.relationship("User", foreign_keys=[rejected_by])


class SaleReceiptItem(db.Model):
    """BASIC section — CC-grouped rows with Booked/Received/Balance/Current."""

    __tablename__ = "sale_receipt_items"

    id         = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(
        db.Integer,
        db.ForeignKey("sale_receipt_billing.id"),
        nullable=False,
    )

    sl_no           = db.Column(db.Integer,       nullable=False)
    cc_code         = db.Column(db.String(50),     nullable=True)
    cc_name         = db.Column(db.String(200),    nullable=True)
    booked_amount   = db.Column(db.Numeric(14, 2), default=0)
    received_amount = db.Column(db.Numeric(14, 2), default=0)
    balance_amount  = db.Column(db.Numeric(14, 2), default=0)
    current_amount  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SaleReceiptGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per billing."""

    __tablename__ = "sale_receipt_gst"

    id         = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(
        db.Integer,
        db.ForeignKey("sale_receipt_billing.id"),
        nullable=False,
    )

    gst_type        = db.Column(db.String(10),    nullable=False)
    cc_code         = db.Column(db.String(50),    nullable=True)
    cc_name         = db.Column(db.String(200),   nullable=True)
    percent         = db.Column(db.Numeric(5, 2),  default=0)
    booked_amount   = db.Column(db.Numeric(14, 2), default=0)
    received_amount = db.Column(db.Numeric(14, 2), default=0)
    balance_amount  = db.Column(db.Numeric(14, 2), default=0)
    current_amount  = db.Column(db.Numeric(14, 2), default=0)
    is_selected     = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
