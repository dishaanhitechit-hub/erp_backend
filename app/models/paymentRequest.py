# app/models/paymentRequest.py
# Payment Request — raised against an Approved BRR (Bill Receive Register).
# Multiple (partial) requests are allowed per BRR; the sum of non-rejected
# requested amounts can never exceed the BRR's bill amount.

from app.extensions import db
from datetime import datetime
import uuid as _uuid_lib


class PaymentRequestMaster(db.Model):

    __tablename__ = "payment_request_master"

    id = db.Column(db.Integer, primary_key=True)

    pr_no   = db.Column(db.String(50), unique=True, nullable=False)
    pr_date = db.Column(db.Date, nullable=False)

    pr_uuid = db.Column(db.String(36), unique=True, nullable=True,
                        default=lambda: str(_uuid_lib.uuid4()))

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    brr_id = db.Column(
        db.Integer,
        db.ForeignKey("brr_master.id"),
        nullable=False,
        index=True
    )

    # Snapshots from the BRR at the time of raising
    brr_no         = db.Column(db.String(50),  nullable=True)
    vendor_id      = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True)
    order_category = db.Column(db.String(100), nullable=True)
    party_bill_no  = db.Column(db.String(100), nullable=True)
    party_date     = db.Column(db.Date,        nullable=True)

    # Financials
    bill_amount          = db.Column(db.Numeric(14, 2), default=0)  # BRR / approved BRB total
    previously_requested = db.Column(db.Numeric(14, 2), default=0)  # other active requests on same BRR
    requested_amount     = db.Column(db.Numeric(14, 2), default=0)  # gross portion of bill claimed
    deduction_amount     = db.Column(db.Numeric(14, 2), default=0)
    deduction_remarks    = db.Column(db.String(500),    nullable=True)
    net_payable          = db.Column(db.Numeric(14, 2), default=0)  # requested - deduction

    payment_mode     = db.Column(db.String(30), nullable=True)   # Bank / Cash
    required_by_date = db.Column(db.Date,       nullable=True)
    remarks          = db.Column(db.Text,       nullable=True)

    attached_doc = db.Column(db.String(500), nullable=True)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,    default=0)
    locked          = db.Column(db.Boolean,    default=False)

    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_by  = db.Column(db.Integer, db.ForeignKey("users.id"))

    submitted_at       = db.Column(db.DateTime)
    final_approved_at  = db.Column(db.DateTime)
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project = db.relationship("Project",   backref="payment_request_list")
    brr     = db.relationship("BrrMaster", backref="payment_requests")
    vendor  = db.relationship("Vendor",    backref="payment_request_list")

    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
