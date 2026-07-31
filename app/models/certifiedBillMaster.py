from app.extensions import db
from datetime import datetime


class CertifiedBillMaster(db.Model):

    __tablename__ = "certified_bill_master"

    id = db.Column(db.Integer, primary_key=True)

    certified_bill_no   = db.Column(db.String(50), unique=True, nullable=False)
    certified_bill_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    certified_bill_date = db.Column(db.Date, nullable=False)

    order_no   = db.Column(db.String(50), nullable=False)
    order_id   = db.Column(db.Integer, nullable=True)
    order_type = db.Column(db.String(10), nullable=False)  # 'normal' or 'pw'

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    title        = db.Column(db.String(200), nullable=True)
    job_location = db.Column(db.String(200), nullable=True)

    # Financial
    pre_certified_amount = db.Column(db.Numeric(14, 2), default=0)
    this_bill_claim      = db.Column(db.Numeric(14, 2), default=0)
    gst_amount           = db.Column(db.Numeric(14, 2), default=0)
    total_claim          = db.Column(db.Numeric(14, 2), default=0)

    attachment = db.Column(db.Text, nullable=True)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

    # Audit
    created_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at      = db.Column(db.DateTime)
    approved_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at = db.Column(db.DateTime)
    rejected_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at       = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project  = db.relationship("Project", backref="certified_bills")
    items    = db.relationship(
        "CertifiedBillItem",
        backref="certified_bill",
        cascade="all,delete-orphan"
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class CertifiedBillItem(db.Model):

    __tablename__ = "certified_bill_items"

    id = db.Column(db.Integer, primary_key=True)

    certified_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("certified_bill_master.id"),
        nullable=False
    )

    sl_no          = db.Column(db.Integer,       nullable=False)
    item_code      = db.Column(db.String(50),    nullable=True)
    item_name_desc = db.Column(db.Text,          nullable=True)
    unit           = db.Column(db.String(30),    nullable=True)
    claim_qty      = db.Column(db.Numeric(12, 2), default=0)
    rate           = db.Column(db.Numeric(12, 2), default=0)
    amount         = db.Column(db.Numeric(14, 2), default=0)
    gst_percent    = db.Column(db.Numeric(5,  2), default=0)
    gst_amount     = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
