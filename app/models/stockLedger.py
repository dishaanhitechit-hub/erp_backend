"""
Stock Ledger model — matches the proposed stock_ledger table in PRAX_SCHEMA_PROPOSAL_v2.md §5.

APPLICATION CODE ONLY: This model does NOT create the table.
The DBA must run the migration from the schema proposal to create the table
before this model is usable at runtime.
"""
from datetime import datetime
from app.extensions import db


class StockLedger(db.Model):
    __tablename__ = "stock_ledger"

    id = db.Column(db.Integer, primary_key=True)
    transaction_date = db.Column(db.Date, nullable=False)
    financial_year_id = db.Column(
        db.Integer, db.ForeignKey("financial_year.id"), nullable=True
    )

    source_type = db.Column(db.String(50), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    source_line_id = db.Column(db.Integer, nullable=True)

    item_id = db.Column(db.Integer, nullable=False)
    item_code = db.Column(db.String(100), nullable=True)
    item_description = db.Column(db.Text, nullable=True)

    project_code = db.Column(
        db.String(50), db.ForeignKey("projects.project_code"), nullable=True
    )
    location_id = db.Column(db.String(150), nullable=True)

    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    rate = db.Column(db.Numeric(14, 2), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)

    valuation_method = db.Column(
        db.String(20), default="WEIGHTED_AVG", nullable=False
    )

    running_qty = db.Column(db.Numeric(14, 3), nullable=True)
    running_value = db.Column(db.Numeric(14, 2), nullable=True)

    is_reversal = db.Column(db.Boolean, default=False, nullable=False)
    reversed_stock_entry_id = db.Column(
        db.Integer, db.ForeignKey("stock_ledger.id"), nullable=True
    )

    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── relationships ──────────────────────────────────────────────
    financial_year = db.relationship("FinancialYear")
    project = db.relationship("Project")
    reversed_entry = db.relationship(
        "StockLedger", remote_side=[id],
        foreign_keys=[reversed_stock_entry_id],
    )
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index(
            "uq_stock_original", "source_type", "source_id", "source_line_id",
            unique=True,
            postgresql_where=db.text("is_reversal = FALSE"),
        ),
        db.Index(
            "uq_stock_one_reversal", "reversed_stock_entry_id",
            unique=True,
            postgresql_where=db.text(
                "is_reversal = TRUE AND reversed_stock_entry_id IS NOT NULL"
            ),
        ),
        db.Index("ix_stock_item", "item_id", "transaction_date"),
        db.Index("ix_stock_project", "project_code"),
        db.Index("ix_stock_date", "transaction_date"),
    )

    def __repr__(self):
        direction = "REV" if self.is_reversal else ("IN" if self.quantity > 0 else "OUT")
        return f"<StockLedger {direction} {self.item_code} qty={self.quantity}>"
