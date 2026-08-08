from app.extensions import db
from datetime import datetime


class SaleReceiptMaster(db.Model):
    """Big parent receipt — holds payment / UTR details only, no workflow."""

    __tablename__ = "sale_receipt_master"

    id           = db.Column(db.Integer, primary_key=True)
    receipt_no   = db.Column(db.String(50), nullable=False)
    receipt_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    entry_date   = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False,
    )

    payment_mode    = db.Column(db.String(10),   nullable=True)
    cash_ac_id      = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)
    bank_ac_id      = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)
    utr_voucher_no  = db.Column(db.String(200),  nullable=True)
    payment_remarks = db.Column(db.Text,         nullable=True)

    total_amount = db.Column(db.Numeric(14, 2), default=0)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project      = db.relationship("Project",  backref="sale_receipts")
    cash_account = db.relationship("BankCash", foreign_keys=[cash_ac_id])
    bank_account = db.relationship("BankCash", foreign_keys=[bank_ac_id])
    creator      = db.relationship("User", foreign_keys=[created_by])
    updater      = db.relationship("User", foreign_keys=[updated_by])
    billings     = db.relationship(
        "SaleReceiptBillingMaster",
        backref="receipt",
        cascade="all,delete-orphan",
    )
