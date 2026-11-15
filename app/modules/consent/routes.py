from flask import Blueprint
from app.middleware.auth_middleware import login_required
from .service import get_consent_status, accept_consent

consent_bp = Blueprint("consent", __name__)


@consent_bp.route("/status", methods=["GET"])
@login_required
def consent_status_route():
    return get_consent_status()


@consent_bp.route("/accept", methods=["POST"])
@login_required
def consent_accept_route():
    return accept_consent()
