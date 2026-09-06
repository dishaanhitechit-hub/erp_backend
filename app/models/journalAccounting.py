from app.extensions import db
from datetime import datetime


class PettyCashJournalAccounting(db.Model):
    __tablename__ = "petty_cash_journal_accounting"

    id                 = db.Column(db.Integer, primary_key=True)
    voucher_no         = db.Column(db.String(50), nullable=False)
    voucher_uuid       = db.Column(db.String(36), unique=True, nullable=True, index=True)
    voucher_date       = db.Column(db.Date, nullable=False)
    journal_voucher_id = db.Column(
        db.Integer,
        db.ForeignKey("petty_cash_journal_voucher.id"),
        unique=True,
        nullable=False,
    )
    project_code  = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)
    total_amount  = db.Column(db.Numeric(14, 2), default=0)

    workflow_status   = db.Column(db.String(30), default="Draft")
    current_level     = db.Column(db.Integer, default=0)
    locked            = db.Column(db.Boolean, default=False)

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

    project         = db.relationship("Project", backref="petty_cash_journal_accountings")
    journal_voucher = db.relationship(
        "PettyCashJournalVoucher",
        backref=db.backref("accounting", uselist=False),
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    lines     = db.relationship(
        "PettyCashJournalAccountingLine",
        backref="journal_accounting",
        cascade="all,delete-orphan",
    )


class PettyCashJournalAccountingLine(db.Model):
    __tablename__ = "petty_cash_journal_accounting_line"

    id                    = db.Column(db.Integer, primary_key=True)
    journal_accounting_id = db.Column(
        db.Integer,
        db.ForeignKey("petty_cash_journal_accounting.id"),
        nullable=False,
    )
    journal_line_id = db.Column(
        db.Integer,
        db.ForeignKey("petty_cash_journal_line.id"),
        unique=True,
        nullable=False,
    )
    sl_no             = db.Column(db.Integer, nullable=False)
    cc_code           = db.Column(db.String(50), nullable=True)
    cc_name           = db.Column(db.String(100), nullable=True)
    short_description = db.Column(db.String(255), nullable=True)
    original_amount   = db.Column(db.Numeric(14, 2), default=0)
    amount            = db.Column(db.Numeric(14, 2), default=0)

    journal_line = db.relationship("PettyCashJournalLine", foreign_keys=[journal_line_id])
