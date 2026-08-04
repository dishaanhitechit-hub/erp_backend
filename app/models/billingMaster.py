from app.extensions import db
from datetime import datetime


class BillingMaster(db.Model):

    __tablename__ = "billing_master"

    id = db.Column(db.Integer, primary_key=True)

    billing_no   = db.Column(db.String(50), nullable=False)
    billing_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    billing_date = db.Column(db.Date, nullable=False)

    # mode: 'sale_order_bill' or 'certified_bill'
    mode = db.Column(db.String(30), nullable=False)

    # For certified_bill: link back to the parent sale_claim_bill
    claim_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Reference to OG Sale Order (both modes use this)
    og_sale_order_no = db.Column(db.String(50), nullable=True)
    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=True,
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    title        = db.Column(db.String(500), nullable=True)
    job_location = db.Column(db.String(500), nullable=True)
    attachment   = db.Column(db.Text, nullable=True)

    # Financials
    pre_certified_amount = db.Column(db.Numeric(14, 2), default=0)
    this_bill_claim      = db.Column(db.Numeric(14, 2), default=0)
    gst_amount           = db.Column(db.Numeric(14, 2), default=0)
    total_claim          = db.Column(db.Numeric(14, 2), default=0)

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
    project  = db.relationship("Project", backref="billing_records")
    og_so    = db.relationship("OgSaleOrderMaster", backref="billing_records")
    items    = db.relationship(
        "BillingItem",
        backref="billing",
        cascade="all,delete-orphan",
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class BillingItem(db.Model):

    __tablename__ = "billing_items"

    id = db.Column(db.Integer, primary_key=True)

    billing_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id"),
        nullable=False,
    )

    sl_no          = db.Column(db.Integer,    nullable=False)
    item_code      = db.Column(db.String(50), nullable=True)
    item_name      = db.Column(db.Text,       nullable=True)
    item_name_desc = db.Column(db.Text,       nullable=True)
    unit           = db.Column(db.String(30), nullable=True)

    claim_qty   = db.Column(db.Numeric(12, 2), default=0)
    rate        = db.Column(db.Numeric(12, 2), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BillingBoqItem(db.Model):
    """BOQ items table — same structure as BillingItem, all manual entry."""

    __tablename__ = "billing_boq_items"

    id = db.Column(db.Integer, primary_key=True)

    billing_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id"),
        nullable=False,
    )

    sl_no          = db.Column(db.Integer,    nullable=False)
    item_code      = db.Column(db.String(50), nullable=True)
    item_name      = db.Column(db.Text,       nullable=True)
    item_name_desc = db.Column(db.Text,       nullable=True)
    unit           = db.Column(db.String(30), nullable=True)

    claim_qty   = db.Column(db.Numeric(12, 2), default=0)
    rate        = db.Column(db.Numeric(12, 2), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
