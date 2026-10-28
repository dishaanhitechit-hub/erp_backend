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

    # Claim bill reference (source of this line's claim amount)
    billing_id = db.Column(
        db.Integer,
        db.ForeignKey("billing_master.id", ondelete="SET NULL"),
        nullable=True,
    )
    billing_no = db.Column(db.String(50), nullable=True)

    # Item-level columns (one row per BOQ/non-BOQ item)
    og_sale_order_item_id = db.Column(db.Integer,      nullable=True)  # PK of OgSaleOrderItem or OgSaleOrderBoqItem
    item_type             = db.Column(db.String(20),   nullable=True)  # 'item' or 'boq_item'
    boq_sl_no             = db.Column(db.Integer,      nullable=True)
    item_code             = db.Column(db.String(100),  nullable=True)
    item_name             = db.Column(db.String(2000), nullable=True)
    item_name_desc        = db.Column(db.Text,         nullable=True)
    unit                  = db.Column(db.String(30),   nullable=True)
    og_boq_qty            = db.Column(db.Numeric(17, 4), nullable=True)   # original sale order ordered qty
    boq_qty               = db.Column(db.Numeric(17, 4), nullable=True)   # claim qty (from claim bill)
    certified_qty         = db.Column(db.Numeric(17, 4), nullable=True)   # certified qty
    unit_rate             = db.Column(db.Numeric(17, 4), nullable=True)

    # Computed amounts (qty × unit_rate), stored for fast aggregation
    claim_amount     = db.Column(db.Numeric(14, 2), default=0)
    certified_amount = db.Column(db.Numeric(14, 2), default=0)
    difference       = db.Column(db.Numeric(14, 2), default=0)

    # Manual justification — stored as QTY; amount = qty × unit_rate
    over_billing_calculation_mistake    = db.Column(db.Numeric(17, 4), default=0)
    certified_hold_amendment_pending    = db.Column(db.Numeric(17, 4), default=0)
    non_boq_items_rate                  = db.Column(db.Numeric(17, 4), default=0)
    hold_work                           = db.Column(db.Numeric(17, 4), default=0)
    hold_for_full_work_not_completed    = db.Column(db.Numeric(17, 4), default=0)

    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    og_sale_order = db.relationship("OgSaleOrderMaster", foreign_keys=[og_sale_order_id])
    claim_bill    = db.relationship("BillingMaster",      foreign_keys=[billing_id])
