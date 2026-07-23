from app.extensions import db
from datetime import datetime


class BrbMaster(db.Model):
    """
    BRB — BRR Billing (unified for GRN and SRN).
    billing_type = "GRN" → items link to grn_items
    billing_type = "SRN" → items link to srn_items
    All order/vendor info is derived at read time via brr → order chain.
    """

    __tablename__ = "brb_master"

    id = db.Column(db.Integer, primary_key=True)

    brb_no   = db.Column(db.String(50), unique=True, nullable=False)
    brb_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    brr_id = db.Column(
        db.Integer,
        db.ForeignKey("brr_master.id"),
        nullable=False
    )

    # "GRN" or "SRN" — drives which order table and approval module to use
    billing_type = db.Column(db.String(10), nullable=False)

    # cached for filtering — auto-filled from BRR chain on create
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)
    order_id  = db.Column(db.Integer, nullable=True)  # order_master.id or pw_order_master.id

    item_category = db.Column(db.String(255), nullable=True)  # JSON array for SRN sub-codes
    cost_head     = db.Column(db.String(100), nullable=True)

    party_bill_no = db.Column(db.String(100), nullable=True)
    party_date    = db.Column(db.Date,        nullable=True)

    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    attached_doc = db.Column(db.Text, nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by  = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at       = db.Column(db.DateTime)
    final_approved_at  = db.Column(db.DateTime)
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    project = db.relationship("Project",   backref="brb_list")
    brr     = db.relationship("BrrMaster", backref="brb_billings")

    items = db.relationship(
        "BrbItem",
        backref="brb",
        cascade="all,delete-orphan"
    )

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])


class BrbItem(db.Model):
    """
    BRB item line. Either grn_item_id or srn_item_id is populated depending on billing_type.
    """

    __tablename__ = "brb_items"

    id = db.Column(db.Integer, primary_key=True)

    brb_id = db.Column(
        db.Integer,
        db.ForeignKey("brb_master.id"),
        nullable=False
    )

    # GRN path
    grn_id      = db.Column(db.Integer, db.ForeignKey("grn_master.id"), nullable=True)
    grn_item_id = db.Column(db.Integer, db.ForeignKey("grn_items.id"),  nullable=True)

    # SRN path
    srn_id      = db.Column(db.Integer, db.ForeignKey("srn_master.id"), nullable=True)
    srn_item_id = db.Column(db.Integer, db.ForeignKey("srn_items.id"),  nullable=True)

    billing_qty = db.Column(db.Numeric(12, 2), default=0)
    rate        = db.Column(db.Numeric(12, 2), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    grn      = db.relationship("GrnMaster", foreign_keys=[grn_id])
    grn_item = db.relationship("GrnItem",   foreign_keys=[grn_item_id])
    srn      = db.relationship("SrnMaster", foreign_keys=[srn_id])
    srn_item = db.relationship("SrnItem",   foreign_keys=[srn_item_id])
