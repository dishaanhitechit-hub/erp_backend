from app.extensions import db
from datetime import datetime


class OgSaleOrderMaster(db.Model):

    __tablename__ = "og_sale_order_master"

    id = db.Column(db.Integer, primary_key=True)

    og_sale_order_no   = db.Column(db.String(50), unique=True, nullable=False)
    og_sale_order_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    og_sale_order_date = db.Column(db.Date, nullable=False)

    order_no       = db.Column(db.String(50),  nullable=True)
    order_validity = db.Column(db.Date,        nullable=True)
    order_title    = db.Column(db.String(200), nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Financials — computed from items
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    # Three attachment slots
    attachment_1 = db.Column(db.Text, nullable=True)
    attachment_2 = db.Column(db.Text, nullable=True)
    attachment_3 = db.Column(db.Text, nullable=True)

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
    project  = db.relationship("Project", backref="og_sale_orders")
    items    = db.relationship(
        "OgSaleOrderItem",
        backref="og_sale_order",
        cascade="all,delete-orphan"
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class OgSaleOrderItem(db.Model):

    __tablename__ = "og_sale_order_items"

    id = db.Column(db.Integer, primary_key=True)

    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=False
    )

    sl_no          = db.Column(db.Integer,        nullable=False)
    item_code      = db.Column(db.String(50),     nullable=True)   # manual text
    item_name_desc = db.Column(db.Text,           nullable=True)   # manual text
    unit           = db.Column(db.String(30),     nullable=True)   # manual text
    order_qty      = db.Column(db.Numeric(12, 2), default=0)
    rate           = db.Column(db.Numeric(12, 2), default=0)
    amount         = db.Column(db.Numeric(14, 2), default=0)       # order_qty × rate
    gst_percent    = db.Column(db.Numeric(5,  2), default=0)
    gst_amount     = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
