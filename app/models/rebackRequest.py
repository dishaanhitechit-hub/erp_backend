"""
Reback request — someone asks for a fully approved record to be sent back.

The final approver of that module (or an admin) accepts or declines it.
Accepting undoes the approval (see app/modules/workflow/unapprove.py).
Only one PENDING request per record at a time (partial unique index).
"""
from datetime import datetime

from app.extensions import db


class RebackRequest(db.Model):
    __tablename__ = "reback_requests"

    id = db.Column(db.Integer, primary_key=True)

    module    = db.Column(db.String(50), nullable=False, index=True)   # key in workflow/bulk.py BULK_MODULES
    record_id = db.Column(db.Integer, nullable=False)
    record_no = db.Column(db.String(100), nullable=True)
    project_code = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=True, index=True)
    approval_module = db.Column(db.String(50), nullable=True)   # approval-path module code (who is final approver)
    page_url        = db.Column(db.String(255), nullable=True)  # app page the request was raised from (link back)

    status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    # PENDING / ACCEPTED / DECLINED / CANCELLED

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reason       = db.Column(db.Text, nullable=False)

    decided_by       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at       = db.Column(db.DateTime, nullable=True)
    decision_comment = db.Column(db.Text, nullable=True)

    requester = db.relationship("User", foreign_keys=[requested_by])
    decider   = db.relationship("User", foreign_keys=[decided_by])

    __table_args__ = (
        db.Index("ix_reback_request_record", "module", "record_id"),
        db.Index("uq_reback_request_open", "module", "record_id", unique=True,
                 postgresql_where=db.text("status = 'PENDING'")),
    )
