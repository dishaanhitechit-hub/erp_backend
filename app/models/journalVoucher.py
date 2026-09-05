from app.extensions import db
from datetime import datetime


class PettyCashJournalVoucher(db.Model):
    __tablename__ = "petty_cash_journal_voucher"

    id            = db.Column(db.Integer, primary_key=True)
    voucher_no    = db.Column(db.String(50), nullable=False)
    voucher_uuid  = db.Column(db.String(36), unique=True, nullable=True, index=True)
    voucher_date  = db.Column(db.Date, nullable=False)
    fund_source   = db.Column(db.String(20), nullable=False)  # Cash / Bank
    project_code  = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)
    total_amount  = db.Column(db.Numeric(14, 2), default=0)

    workflow_status   = db.Column(db.String(30), default="Draft")
    current_level     = db.Column(db.Integer,    default=0)
    locked            = db.Column(db.Boolean,    default=False)

    submitted_by      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    submitted_at      = db.Column(db.DateTime, nullable=True)
    approved_by       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    final_approved_at = db.Column(db.DateTime, nullable=True)
    rejected_by       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejected_at       = db.Column(db.DateTime, nullable=True)
    created_by        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project   = db.relationship("Project", backref="petty_cash_journal_vouchers")
    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    lines     = db.relationship(
        "PettyCashJournalLine",
        backref="journal_voucher",
        cascade="all,delete-orphan",
    )


class PettyCashJournalLine(db.Model):
    __tablename__ = "petty_cash_journal_line"

    id                 = db.Column(db.Integer, primary_key=True)
    journal_voucher_id = db.Column(db.Integer, db.ForeignKey("petty_cash_journal_voucher.id"), nullable=False)
    docket_voucher_id  = db.Column(db.Integer, db.ForeignKey("petty_cash_docket_voucher.id"), nullable=False)
    docket_detail_id   = db.Column(
        db.Integer,
        db.ForeignKey("petty_cash_docket_voucher_detail.id"),
        unique=True,
        nullable=False,
    )
    sl_no             = db.Column(db.Integer,      nullable=False)
    cc_code           = db.Column(db.String(50),   nullable=True)
    cc_name           = db.Column(db.String(100),  nullable=True)
    short_description = db.Column(db.String(255),  nullable=True)
    amount            = db.Column(db.Numeric(14, 2), default=0)

    docket_voucher = db.relationship("PettyCashDocketVoucher",      foreign_keys=[docket_voucher_id])
    docket_detail  = db.relationship("PettyCashDocketVoucherDetail", foreign_keys=[docket_detail_id])
