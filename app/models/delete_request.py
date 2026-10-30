from app.extensions import db
from datetime import datetime


class DeleteRequest(db.Model):
    """
    Tracks every pending / completed cascading delete request.
    When a user wants to delete a record that has downstream children,
    a row is created here.  The system notifies the downstream owner
    via WhatsApp.  Once all children are gone the parent auto-deletes
    and this row is marked COMPLETED.
    """

    __tablename__ = "delete_requests"

    id = db.Column(db.Integer, primary_key=True)

    # Which module and which record is being requested for deletion
    module_code = db.Column(db.String(50),  nullable=False, index=True)
    record_id   = db.Column(db.Integer,     nullable=False)
    record_no   = db.Column(db.String(100), nullable=True)   # human-readable doc number

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=True,
    )

    # Who raised the request
    requested_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Why they want it deleted
    reason = db.Column(db.Text, nullable=True)

    # PENDING  → waiting for downstream to be cleared
    # COMPLETED → all children gone, parent deleted
    # CANCELLED → request was withdrawn
    status = db.Column(db.String(20), default="PENDING", nullable=False, index=True)

    # Snapshot of which child modules are blocking (JSON list of strings)
    # e.g. '["GRN", "PURCHASE_BILL"]'
    blocked_by_modules = db.Column(db.Text, nullable=True)

    # Comma-separated list of child record numbers still pending
    blocked_by_docs = db.Column(db.Text, nullable=True)

    # WhatsApp notification tracking
    wa_sent    = db.Column(db.Boolean, default=False)
    wa_sent_at = db.Column(db.DateTime, nullable=True)

    # Completion
    completed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    cancelled_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    project       = db.relationship("Project", backref="delete_requests")
    requester     = db.relationship("User", foreign_keys=[requested_by])
    canceller     = db.relationship("User", foreign_keys=[cancelled_by])

    def to_dict(self):
        import json
        return {
            "id":                  self.id,
            "module_code":         self.module_code,
            "record_id":           self.record_id,
            "record_no":           self.record_no,
            "project_code":        self.project_code,
            "requested_by":        self.requested_by,
            "requested_at":        self.requested_at.isoformat() if self.requested_at else None,
            "reason":              self.reason,
            "status":              self.status,
            "blocked_by_modules":  json.loads(self.blocked_by_modules) if self.blocked_by_modules else [],
            "blocked_by_docs":     self.blocked_by_docs or "",
            "wa_sent":             self.wa_sent,
            "wa_sent_at":          self.wa_sent_at.isoformat() if self.wa_sent_at else None,
            "completed_at":        self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_at":        self.cancelled_at.isoformat() if self.cancelled_at else None,
        }
