from app.extensions import db
from datetime import datetime, timezone

CURRENT_CONSENT_VERSION = "1.0"


class EmployeeConsent(db.Model):
    __tablename__ = "employee_consent"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_version = db.Column(db.String(20), nullable=False)
    accepted = db.Column(db.Boolean, default=False, nullable=False)
    accepted_at = db.Column(db.DateTime)
    # keys: ack_data_collection, ack_confidentiality, ack_financial_info,
    #       ack_activity_logs, ack_responsibilities, final_consent
    acknowledgements = db.Column(db.JSON, default=dict)
    final_consent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=datetime.now
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "document_version", name="uq_employee_consent_user_version"
        ),
    )

    user = db.relationship("User", backref=db.backref("consents", lazy="dynamic"))
