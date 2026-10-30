from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import CommCall, CommCallParticipant

try:
    from app.modules.hr.employee_tracking.tracking_service import get_user_last_seen
    _HAS_TRACKING = True
except ImportError:
    _HAS_TRACKING = False


def _now():
    return datetime.now(timezone.utc)


def get_rich_status(user_id: int) -> dict:
    """Return aggregated presence/status info for a user."""
    in_call   = _is_in_call(user_id)
    last_seen = _get_last_seen(user_id)

    # Without tracking, active users in the directory are presumed online
    status = "in_call" if in_call else ("online" if (last_seen or not _HAS_TRACKING) else "offline")

    return {
        "userId":   user_id,
        "status":   status,
        "inCall":   in_call,
        "lastSeen": last_seen,
    }


def get_user_directory(requesting_user_id: int, search: str = None) -> list:
    """Return basic user list for the in-app directory / @mention lookup."""
    from app.models.user import User

    query = User.query.filter_by(is_active=True)
    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f"%{search}%"),
                User.emp_code.ilike(f"%{search}%"),
            )
        )

    users = query.order_by(User.username.asc()).limit(100).all()
    return [
        {
            "userId":   u.id,
            "userName": u.username,
            "empCode":  u.emp_code,
            **get_rich_status(u.id),
        }
        for u in users
        if u.id != requesting_user_id
    ]


def set_communication_status(user_id: int, status: str) -> bool:
    """Placeholder — update status if a custom status model is added later."""
    return True


def _is_in_call(user_id: int) -> bool:
    try:
        return db.session.query(CommCallParticipant).join(CommCall).filter(
            CommCallParticipant.user_id == user_id,
            CommCallParticipant.state   == "in_call",
            CommCall.status             == "active",
        ).first() is not None
    except Exception:
        return False


def _get_last_seen(user_id: int) -> str | None:
    if not _HAS_TRACKING:
        return None
    try:
        ts = get_user_last_seen(user_id)
        return ts.strftime("%Y-%m-%d %H:%M:%S") if ts else None
    except Exception:
        return None
