from app.extensions import db
from datetime import datetime


class SaleBillMaster(db.Model):

    __tablename__ = "sale_bill_master"

    id = db.Column(db.Integer, primary_key=True)

    sale_bill_no   = db.Column(db.String(50), nullable=False)
    sale_bill_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    # sale_invoice or proforma_invoice
    mode         = db.Column(db.String(30), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False)

    reference_no   = db.Column(db.String(200), nullable=True)
    reference_date = db.Column(db.Date, nullable=True)

    # OG Sale Order reference
    sale_order_no = db.Column(db.String(50), nullable=True)
    sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=True,
    )

    # Linked approved certified bill
    certified_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id"),
        nullable=True,
    )
    certified_bill_no = db.Column(db.String(50), nullable=True)  # snapshot

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    bill_to_address  = db.Column(db.Text, nullable=True)
    ship_to_address  = db.Column(db.Text, nullable=True)

    bill_abstract_no   = db.Column(db.String(200), nullable=True)
    bill_abstract_date = db.Column(db.Date, nullable=True)

    bank_ac       = db.Column(db.String(200), nullable=True)
    bank_ac_id    = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)
    payment_terms = db.Column(db.Text, nullable=True)
    declaration   = db.Column(db.Text, nullable=True)

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
    project        = db.relationship("Project",             backref="sale_bills")
    og_so          = db.relationship("OgSaleOrderMaster",   backref="sale_bills")
    certified_bill = db.relationship("BillingMaster",       backref="sale_bills")
    bank_account   = db.relationship("BankCash", foreign_keys=[bank_ac_id])
    items          = db.relationship("SaleBillItem", backref="sale_bill", cascade="all,delete-orphan")
    gst_lines      = db.relationship("SaleBillGst",  backref="sale_bill", cascade="all,delete-orphan")
    creator        = db.relationship("User", foreign_keys=[created_by])
    updater        = db.relationship("User", foreign_keys=[updated_by])
    submitter      = db.relationship("User", foreign_keys=[submitted_by])
    approver       = db.relationship("User", foreign_keys=[approved_by])
    rejector       = db.relationship("User", foreign_keys=[rejected_by])


class SaleBillItem(db.Model):
    """BASIC section — one row per CC Code group."""

    __tablename__ = "sale_bill_items"

    id           = db.Column(db.Integer, primary_key=True)
    sale_bill_id = db.Column(db.Integer, db.ForeignKey("sale_bill_master.id"), nullable=False)

    sl_no        = db.Column(db.Integer, nullable=False)
    cc_code      = db.Column(db.String(50),  nullable=True)
    cc_name      = db.Column(db.String(200), nullable=True)
    description  = db.Column(db.Text,        nullable=True)
    hsn_sac      = db.Column(db.String(50),  nullable=True)
    basic_amount = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SaleBillGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per bill."""

    __tablename__ = "sale_bill_gst"

    id           = db.Column(db.Integer, primary_key=True)
    sale_bill_id = db.Column(db.Integer, db.ForeignKey("sale_bill_master.id"), nullable=False)

    gst_type    = db.Column(db.String(10),   nullable=False)   # IGST / CGST / SGST
    cc_code     = db.Column(db.String(50),   nullable=True)
    cc_name     = db.Column(db.String(200),  nullable=True)
    description = db.Column(db.Text,         nullable=True)
    percent     = db.Column(db.Numeric(5, 2),  default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)
    is_selected = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
