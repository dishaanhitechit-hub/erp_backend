from datetime import datetime, timezone
from flask import g, request as flask_request
from app.extensions import db
from app.response import res
from app.models.employeeConsent import EmployeeConsent, CURRENT_CONSENT_VERSION

REQUIRED_ACKS = [
    "ack_data_collection",
    "ack_confidentiality",
    "ack_financial_info",
    "ack_activity_logs",
    "ack_responsibilities",
]


def _user_has_accepted(user_id: int, version: str = CURRENT_CONSENT_VERSION) -> bool:
    record = EmployeeConsent.query.filter_by(
        user_id=user_id, document_version=version, accepted=True
    ).first()
    return record is not None


def get_consent_status():
    user_id = g.current_user["id"]
    required = not _user_has_accepted(user_id)
    return res("Consent status", [{
        "consent_required": required,
        "document_version": CURRENT_CONSENT_VERSION,
    }])


def accept_consent():
    user_id = g.current_user["id"]

    # Idempotency: if already accepted for this version, return success
    if _user_has_accepted(user_id):
        return res("Consent already recorded", [{
            "consent_required": False,
            "document_version": CURRENT_CONSENT_VERSION,
        }])

    data = flask_request.get_json(silent=True) or {}
    acknowledgements = data.get("acknowledgements", {})
    final_consent = bool(data.get("final_consent", False))

    # Validate all required acks are present and truthy
    missing = [k for k in REQUIRED_ACKS if not acknowledgements.get(k)]
    if missing:
        return res(f"Missing acknowledgements: {', '.join(missing)}", code=400)

    if not final_consent:
        return res("Final consent checkbox is required", code=400)

    # Collect optional metadata (do not block on failure)
    ip_address = flask_request.remote_addr
    user_agent = flask_request.headers.get("User-Agent", "")[:512]

    try:
        record = EmployeeConsent(
            user_id=user_id,
            document_version=CURRENT_CONSENT_VERSION,
            accepted=True,
            accepted_at=datetime.now(timezone.utc),
            acknowledgements={k: bool(acknowledgements.get(k)) for k in REQUIRED_ACKS},
            final_consent=True,
        )
        db.session.add(record)
        db.session.commit()
        return res("Consent accepted", [{
            "consent_required": False,
            "document_version": CURRENT_CONSENT_VERSION,
        }])
    except Exception:
        db.session.rollback()
        return res("Failed to record consent. Please try again.", code=500)


def consent_status_for_login(user_id: int) -> bool:
    """Returns True when the user must accept the current consent document."""
    return not _user_has_accepted(user_id)
