from app.extensions import db
from datetime import datetime


class PurchaseBillMaster(db.Model):

    __tablename__ = "purchase_bill_master"

    id = db.Column(db.Integer, primary_key=True)

    purchase_bill_no   = db.Column(db.String(50), nullable=False)
    purchase_bill_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    # purchase_invoice or proforma_invoice
    mode            = db.Column(db.String(30), nullable=False)
    processing_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)

    # "GRN" → order_master, "SRN" → pw_order_master
    order_type  = db.Column(db.String(10), nullable=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("order_master.id"),    nullable=True)
    pw_order_id = db.Column(db.Integer, db.ForeignKey("pw_order_master.id"), nullable=True)

    # BRR reference
    brr_id   = db.Column(db.Integer, db.ForeignKey("brr_master.id"), nullable=True)
    brr_no   = db.Column(db.String(50), nullable=True)  # snapshot
    brr_date = db.Column(db.Date,       nullable=True)  # snapshot

    vendor_bill_no   = db.Column(db.String(100), nullable=True)  # party_bill_no snapshot
    vendor_bill_date = db.Column(db.Date,        nullable=True)  # party_date snapshot

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
    project   = db.relationship("Project",                backref="purchase_bills")
    vendor    = db.relationship("Vendor",                 backref="purchase_bills")
    order     = db.relationship("OrderMaster",            backref="purchase_bills")
    pw_order  = db.relationship("ProjectWorkOrderMaster", backref="purchase_bills")
    brr       = db.relationship("BrrMaster",              backref="purchase_bills")

    items     = db.relationship("PurchaseBillItem", backref="purchase_bill", cascade="all,delete-orphan")
    gst_lines = db.relationship("PurchaseBillGst",  backref="purchase_bill", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class PurchaseBillItem(db.Model):
    """BASIC section — one row per CC Code group."""

    __tablename__ = "purchase_bill_items"

    id               = db.Column(db.Integer, primary_key=True)
    purchase_bill_id = db.Column(db.Integer, db.ForeignKey("purchase_bill_master.id"), nullable=False)

    sl_no        = db.Column(db.Integer,        nullable=False)
    cc_code      = db.Column(db.String(50),     nullable=True)
    cc_name      = db.Column(db.String(200),    nullable=True)
    description  = db.Column(db.Text,           nullable=True)
    hsn_sac      = db.Column(db.String(50),     nullable=True)
    basic_amount = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PurchaseBillGst(db.Model):
    """GST section — up to 3 rows (IGST / CGST / SGST) per bill."""

    __tablename__ = "purchase_bill_gst"

    id               = db.Column(db.Integer, primary_key=True)
    purchase_bill_id = db.Column(db.Integer, db.ForeignKey("purchase_bill_master.id"), nullable=False)

    gst_type    = db.Column(db.String(10),    nullable=False)  # IGST / CGST / SGST
    cc_code     = db.Column(db.String(50),    nullable=True)
    cc_name     = db.Column(db.String(200),   nullable=True)
    description = db.Column(db.Text,          nullable=True)
    percent     = db.Column(db.Numeric(5, 2),  default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)
    is_selected = db.Column(db.Boolean,        default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
