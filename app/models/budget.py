from app.extensions import db
from datetime import datetime


class BudgetMaster(db.Model):

    __tablename__ = "budget_master"

    id = db.Column(db.Integer, primary_key=True)

    budget_no   = db.Column(db.String(50), unique=True, nullable=False)
    budget_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    budget_date = db.Column(db.Date, nullable=False)

    sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=False,
    )
    sale_order_no    = db.Column(db.String(50),  nullable=True)   # snapshot
    sale_order_title = db.Column(db.String(200), nullable=True)   # snapshot

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    remarks = db.Column(db.Text, nullable=True)

    # Financials — computed on save
    total_initial_cost = db.Column(db.Numeric(14, 2), default=0)  # sum of item initial amounts
    total_cc_cost      = db.Column(db.Numeric(14, 2), default=0)  # sum of all CC code costs
    grand_total        = db.Column(db.Numeric(14, 2), default=0)  # initial + cc

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
    project    = db.relationship("Project",           backref="budgets")
    sale_order = db.relationship("OgSaleOrderMaster", backref="budgets")
    items      = db.relationship("BudgetItem", backref="budget", cascade="all,delete-orphan")
    creator    = db.relationship("User", foreign_keys=[created_by])
    updater    = db.relationship("User", foreign_keys=[updated_by])
    submitter  = db.relationship("User", foreign_keys=[submitted_by])
    approver   = db.relationship("User", foreign_keys=[approved_by])
    rejector   = db.relationship("User", foreign_keys=[rejected_by])


class BudgetItem(db.Model):
    """One row per sale order item — snapshot of the item at budget creation time."""

    __tablename__ = "budget_items"

    id        = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey("budget_master.id"), nullable=False)

    # Reference to source sale order item (for traceability)
    og_sale_order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_items.id"),
        nullable=True,
    )

    sl_no            = db.Column(db.Integer,      nullable=False)
    item_code        = db.Column(db.String(50),   nullable=True)
    item_name        = db.Column(db.String(2000), nullable=True)
    item_description = db.Column(db.Text,         nullable=True)
    unit             = db.Column(db.String(30),   nullable=True)

    order_qty      = db.Column(db.Numeric(17, 4), default=0)
    rate           = db.Column(db.Numeric(17, 4), default=0)
    initial_amount = db.Column(db.Numeric(14, 2), default=0)  # order_qty × rate

    # Computed totals for this item
    total_cc_cost  = db.Column(db.Numeric(14, 2), default=0)  # sum of cc line costs
    total_cost     = db.Column(db.Numeric(14, 2), default=0)  # initial_amount + total_cc_cost

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    cc_codes = db.relationship(
        "BudgetItemCCCode",
        backref="budget_item",
        cascade="all,delete-orphan",
    )


class BudgetItemCCCode(db.Model):
    """Many CC codes per budget item — user assigns a unit value per CC code."""

    __tablename__ = "budget_item_cc_codes"

    id             = db.Column(db.Integer, primary_key=True)
    budget_item_id = db.Column(db.Integer, db.ForeignKey("budget_items.id"), nullable=False)

    cc_code_id = db.Column(db.Integer, db.ForeignKey("cc_codes.id"), nullable=False)
    cc_code    = db.Column(db.String(50),  nullable=True)   # snapshot
    cc_name    = db.Column(db.String(200), nullable=True)   # snapshot

    # User-entered value (unit cost for this CC code)
    cc_value = db.Column(db.Numeric(17, 4), default=0)

    # order_qty × cc_value — computed & stored
    cc_total = db.Column(db.Numeric(14, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    cc_code_ref = db.relationship("CCCode", foreign_keys=[cc_code_id])
