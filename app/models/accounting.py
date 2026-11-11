from app.extensions import db
from datetime import datetime


class FinancialYear(db.Model):
    __tablename__ = "financial_year"

    id         = db.Column(db.Integer, primary_key=True)
    fy_code    = db.Column(db.String(10), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date   = db.Column(db.Date, nullable=False)
    is_locked  = db.Column(db.Boolean, default=False)
    is_current = db.Column(db.Boolean, default=False)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<FinancialYear {self.fy_code}>"


class AccountingLedger(db.Model):
    __tablename__ = "accounting_ledger"

    id              = db.Column(db.Integer, primary_key=True)
    posting_date    = db.Column(db.Date, nullable=False)
    financial_year_id = db.Column(db.Integer, db.ForeignKey("financial_year.id"), nullable=True)

    source_type     = db.Column(db.String(50), nullable=False)
    source_id       = db.Column(db.Integer, nullable=False)
    voucher_no      = db.Column(db.String(100), nullable=False)
    project_code    = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=True)
    remarks         = db.Column(db.Text, nullable=True)

    is_reversal         = db.Column(db.Boolean, default=False)
    reversed_posting_id = db.Column(db.Integer, db.ForeignKey("accounting_ledger.id"), nullable=True)

    total_debit   = db.Column(db.Numeric(14, 2), default=0)
    total_credit  = db.Column(db.Numeric(14, 2), default=0)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lines = db.relationship(
        "AccountingLedgerLine", backref="posting",
        cascade="all,delete-orphan",
        order_by="AccountingLedgerLine.sl_no",
    )
    reversed_posting = db.relationship("AccountingLedger", remote_side=[id], foreign_keys=[reversed_posting_id])
    project = db.relationship("Project", backref="accounting_entries")
    creator = db.relationship("User", foreign_keys=[created_by])
    financial_year = db.relationship("FinancialYear", backref="postings")

    __table_args__ = (
        db.CheckConstraint("total_debit = total_credit", name="ck_ledger_balanced"),
        db.Index(
            "uq_ledger_source", "source_type", "source_id",
            unique=True,
            postgresql_where=db.text("is_reversal = FALSE"),
        ),
    )

    def __repr__(self):
        return f"<AccountingLedger {self.voucher_no} ({self.source_type}:{self.source_id})>"


class AccountingLedgerLine(db.Model):
    __tablename__ = "accounting_ledger_lines"

    id         = db.Column(db.Integer, primary_key=True)
    posting_id = db.Column(db.Integer, db.ForeignKey("accounting_ledger.id"), nullable=False)
    sl_no      = db.Column(db.Integer, nullable=False)

    account_type = db.Column(db.String(20), nullable=False)

    cc_id        = db.Column(db.Integer, db.ForeignKey("cc_codes.id"), nullable=True)
    vendor_id    = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)
    bank_cash_id = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=True)

    dr_cr  = db.Column(db.String(2), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)

    project_code     = db.Column(db.String(50), nullable=True)
    cost_centre_code = db.Column(db.String(50), nullable=True)
    gst_type         = db.Column(db.String(10), nullable=True)
    gst_rate         = db.Column(db.Numeric(5, 2), nullable=True)

    source_line_id = db.Column(db.Integer, nullable=True)
    narration      = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cc_code_rel   = db.relationship("CCCode", foreign_keys=[cc_id])
    vendor        = db.relationship("Vendor", foreign_keys=[vendor_id])
    bank_cash_rel = db.relationship("BankCash", foreign_keys=[bank_cash_id])

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_line_positive"),
    )

    def __repr__(self):
        return f"<AccountingLedgerLine {self.dr_cr} {self.account_type} {self.amount}>"
