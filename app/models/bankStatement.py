"""
Bank statement import — batches, transactions and the link audit log.

Re-uses existing masters: bank account = ``bank_cash`` (Master > Bank/Cash),
site = ``projects.project_code`` (there is no separate site master), users.

A transaction is "available" for a petty cash docket when it is a DR,
``reconciliation_status == 'Unreconciled'`` and ``linked_docket_id`` is NULL.
Saving a docket with the transaction reserves it (sets linked_docket_id); final
approval of the docket marks it 'Reconciled'. Reject / delete / unlink release it.
``linked_docket_id`` is UNIQUE, so one transaction ↔ one docket at DB level, and
ON DELETE SET NULL frees the transaction if a docket row is removed by any path.
"""

from datetime import datetime

from app.extensions import db


class BankStatementBatch(db.Model):
    """One uploaded statement file."""

    __tablename__ = "bank_statement_batch"

    id              = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=False, index=True)
    file_name       = db.Column(db.String(255), nullable=True)

    total_rows      = db.Column(db.Integer, default=0)
    imported_count  = db.Column(db.Integer, default=0)
    skipped_count   = db.Column(db.Integer, default=0)   # duplicates
    failed_count    = db.Column(db.Integer, default=0)   # invalid rows
    from_date       = db.Column(db.Date, nullable=True)
    to_date         = db.Column(db.Date, nullable=True)
    total_debit     = db.Column(db.Numeric(15, 2), default=0)
    total_credit    = db.Column(db.Numeric(15, 2), default=0)

    status          = db.Column(db.String(20), default="Active")   # Active / Reverted
    created_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    reverted_by     = db.Column(db.Integer, db.ForeignKey("users.id"))
    reverted_at     = db.Column(db.DateTime)

    bank_account = db.relationship("BankCash", foreign_keys=[bank_account_id])
    creator      = db.relationship("User", foreign_keys=[created_by])
    reverter     = db.relationship("User", foreign_keys=[reverted_by])


class BankTransaction(db.Model):
    """One statement line."""

    __tablename__ = "bank_transaction"
    __table_args__ = (
        db.UniqueConstraint("bank_account_id", "dedupe_key", name="uq_bank_txn_account_dedupe"),
        db.Index("ix_bank_txn_account_site_status", "bank_account_id", "site_code", "reconciliation_status"),
        db.CheckConstraint("transaction_type IN ('DR', 'CR')", name="ck_bank_txn_type"),
    )

    id               = db.Column(db.Integer, primary_key=True)
    bank_account_id  = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=False, index=True)
    import_batch_id  = db.Column(db.Integer, db.ForeignKey("bank_statement_batch.id", ondelete="CASCADE"),
                                 nullable=False, index=True)
    row_no           = db.Column(db.Integer, nullable=True)            # row in the uploaded file

    transaction_date = db.Column(db.Date, nullable=False, index=True)
    by_dr            = db.Column(db.String(200), nullable=True)        # BY-DR party
    to_cr            = db.Column(db.String(200), nullable=True)        # TO-CR party
    debit_amount     = db.Column(db.Numeric(15, 2), default=0)         # DR — outgoing payment
    credit_amount    = db.Column(db.Numeric(15, 2), default=0)         # CR — incoming receipt
    balance          = db.Column(db.Numeric(15, 2), nullable=True)     # running balance
    description      = db.Column(db.String(500), nullable=True)        # DESC / narration
    transaction_type = db.Column(db.String(2), nullable=False)         # DR / CR
    site_code        = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=True, index=True)
    reference_number = db.Column(db.String(100), nullable=True)
    is_upi           = db.Column(db.Boolean, default=False, index=True)  # derived from narration at import
    dedupe_key       = db.Column(db.String(64), nullable=False)        # sha256 of normalised fields

    reconciliation_status = db.Column(db.String(20), default="Unreconciled", nullable=False, index=True)
    linked_docket_id = db.Column(
        db.Integer,
        db.ForeignKey("petty_cash_docket_voucher.id", ondelete="SET NULL"),
        nullable=True, unique=True,
    )
    linked_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    linked_at        = db.Column(db.DateTime)
    reconciled_by    = db.Column(db.Integer, db.ForeignKey("users.id"))
    reconciled_at    = db.Column(db.DateTime)

    created_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    bank_account  = db.relationship("BankCash", foreign_keys=[bank_account_id])
    batch         = db.relationship("BankStatementBatch", backref=db.backref("transactions", passive_deletes=True))
    linked_docket = db.relationship("PettyCashDocketVoucher", foreign_keys=[linked_docket_id],
                                    backref=db.backref("bank_transaction", uselist=False, passive_deletes=True))


class BankTransactionLog(db.Model):
    """Audit trail for every link / unlink / reconcile / revert on a transaction."""

    __tablename__ = "bank_transaction_log"

    id             = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("bank_transaction.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    docket_id      = db.Column(db.Integer, nullable=True)          # kept even if the docket is deleted
    docket_no      = db.Column(db.String(30), nullable=True)
    action         = db.Column(db.String(30), nullable=False)      # LINK / UNLINK / RECONCILE / UNRECONCILE
    note           = db.Column(db.String(255), nullable=True)
    action_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    action_at      = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[action_by])
