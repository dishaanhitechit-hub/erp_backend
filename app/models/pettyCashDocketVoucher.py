from app.extensions import db
from datetime import datetime


class PettyCashDocketVoucher(db.Model):

    __tablename__ = "petty_cash_docket_voucher"

    id           = db.Column(db.Integer, primary_key=True)
    voucher_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    voucher_no   = db.Column(db.String(30), nullable=False)

    voucher_date    = db.Column(db.Date,     nullable=False)
    budget_id       = db.Column(db.Integer,  db.ForeignKey("petty_cash_budget.id"), nullable=True)
    expenses_by     = db.Column(db.String(100), nullable=False)
    mode_of_payment = db.Column(db.String(30),  nullable=False)  # Cash / Cheque / Online / NEFT / RTGS
    fund_source     = db.Column(db.String(50),  nullable=False)
    payment_ref_id  = db.Column(db.String(100), nullable=True)
    attachment      = db.Column(db.String(255), nullable=True)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    total_amount = db.Column(db.Numeric(15, 2), default=0)

    # Workflow
    workflow_status    = db.Column(db.String(30), default="Draft")
    status             = db.Column(db.String(30), default="Active")
    current_level      = db.Column(db.Integer,    default=0)
    locked             = db.Column(db.Boolean,    default=False)

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
    project = db.relationship("Project", backref="petty_cash_docket_vouchers")
    budget  = db.relationship("PettyCashBudget", backref="docket_vouchers", foreign_keys=[budget_id])
    details = db.relationship("PettyCashDocketVoucherDetail", backref="voucher", cascade="all,delete-orphan")

    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class PettyCashDocketVoucherDetail(db.Model):

    __tablename__ = "petty_cash_docket_voucher_detail"

    id         = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("petty_cash_docket_voucher.id"), nullable=False)

    sl_no             = db.Column(db.Integer,     nullable=False)
    cc_code           = db.Column(db.String(20),  nullable=True)
    cc_name           = db.Column(db.String(100), nullable=True)
    short_description = db.Column(db.String(255), nullable=True)
    amount            = db.Column(db.Numeric(15, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
