from app.extensions import db
from datetime import datetime
import uuid as _uuid_lib


class UncertainAllocationMaster(db.Model):

    __tablename__ = "uncertain_allocation_master"

    id = db.Column(db.Integer, primary_key=True)

    ua_no   = db.Column(db.String(50), unique=True, nullable=False)
    ua_date = db.Column(db.Date, nullable=False)
    ua_uuid = db.Column(db.String(36), unique=True, nullable=True,
                        default=lambda: str(_uuid_lib.uuid4()))

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    remarks = db.Column(db.Text, nullable=True)

    # Snapshot totals
    total_claim      = db.Column(db.Numeric(14, 2), default=0)
    total_certified  = db.Column(db.Numeric(14, 2), default=0)
    total_difference = db.Column(db.Numeric(14, 2), default=0)

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
    project = db.relationship("Project", backref="uncertain_allocations")
    lines   = db.relationship(
        "UncertainAllocationLine",
        backref="ua",
        cascade="all,delete-orphan",
        order_by="UncertainAllocationLine.sl_no",
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class UncertainAllocationLine(db.Model):

    __tablename__ = "uncertain_allocation_lines"

    id = db.Column(db.Integer, primary_key=True)

    ua_id = db.Column(
        db.Integer,
        db.ForeignKey("uncertain_allocation_master.id"),
        nullable=False,
    )

    sl_no = db.Column(db.Integer, nullable=False)

    # Sale order reference
    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=True,
    )
    og_sale_order_no = db.Column(db.String(50),  nullable=True)
    order_title      = db.Column(db.String(500), nullable=True)
    order_no         = db.Column(db.String(50),  nullable=True)
    order_date       = db.Column(db.Date,        nullable=True)

    # Auto-computed from BillingMaster at save time
    claim_amount     = db.Column(db.Numeric(14, 2), default=0)
    certified_amount = db.Column(db.Numeric(14, 2), default=0)
    difference       = db.Column(db.Numeric(14, 2), default=0)

    # Manual justification (right-side 4 fields)
    over_billing_calculation_mistake = db.Column(db.Numeric(14, 2), default=0)
    certified_hold_amendment_pending = db.Column(db.Numeric(14, 2), default=0)
    non_boq_items_rate               = db.Column(db.Numeric(14, 2), default=0)
    hold_work                        = db.Column(db.Numeric(14, 2), default=0)

    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    og_sale_order = db.relationship("OgSaleOrderMaster", foreign_keys=[og_sale_order_id])
