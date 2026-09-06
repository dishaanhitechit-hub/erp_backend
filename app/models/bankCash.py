from app.extensions import db
from datetime import datetime


class BankCashProject(db.Model):
    __tablename__ = "bank_cash_project"
    __table_args__ = (
        db.UniqueConstraint("bank_cash_id", "project_id", name="uq_bank_cash_project"),
    )

    id           = db.Column(db.Integer, primary_key=True)
    bank_cash_id = db.Column(db.Integer, db.ForeignKey("bank_cash.id"), nullable=False)
    project_id   = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", foreign_keys=[project_id])


class BankCash(db.Model):
    __tablename__ = "bank_cash"

    id                     = db.Column(db.Integer, primary_key=True)
    type                   = db.Column(db.String(20), nullable=False)
    bank_code              = db.Column(db.String(100), unique=True, nullable=False)
    bank_holder_name       = db.Column(db.String(200), nullable=True)
    bank_account_number    = db.Column(db.String(100), nullable=True)
    bank_name              = db.Column(db.String(200), nullable=True)
    branch_name            = db.Column(db.String(200), nullable=True)
    ifsc_code              = db.Column(db.String(20), nullable=True)
    micr_code              = db.Column(db.String(20), nullable=True)
    customer_id            = db.Column(db.String(100), nullable=True)
    branch_manager_name    = db.Column(db.String(200), nullable=True)
    branch_manager_contact = db.Column(db.String(20), nullable=True)
    branch_manager_email   = db.Column(db.String(200), nullable=True)

    status     = db.Column(db.String(20), default="Active")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator  = db.relationship("User", foreign_keys=[created_by])
    projects = db.relationship("BankCashProject", backref="bank_cash",
                               cascade="all, delete-orphan", lazy="joined")