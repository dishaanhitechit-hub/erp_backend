# app/models/runtime_store.py
"""
Short-lived values shared by every Gunicorn worker and the scheduler process:
OTP codes, password-reset tokens, rate-limit counters, scheduler job leases.

Before this, these lived in a Python dict inside each worker, so with more
than one worker a value saved by one worker was unknown to the others.

Not business data: every row has an expiry and may be deleted at any time
(see app/utils/runtime_store.py).
"""

from app.extensions import db


class RuntimeStore(db.Model):
    __tablename__ = "runtime_store"

    key = db.Column(db.String(200), primary_key=True)
    value = db.Column(db.JSON, nullable=True)
    # UTC, without time zone
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, nullable=False)
