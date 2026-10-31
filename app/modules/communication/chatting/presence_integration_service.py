from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.communication_models import CommCall, CommCallParticipant

try:
    from app.modules.hr.employee_tracking.tracking_service import get_user_last_seen
    _HAS_TRACKING = True
except ImportError:
    _HAS_TRACKING = False

# In-memory heartbeat store — resets on server restart, no migration needed
_heartbeats: dict = {}   # user_id (int) → datetime (utc)
ONLINE_THRESHOLD = timedelta(seconds=90)


def record_heartbeat(user_id: int) -> None:
    _heartbeats[user_id] = datetime.now(timezone.utc)


def _is_online_via_heartbeat(user_id: int) -> bool:
    ts = _heartbeats.get(user_id)
    if not ts:
        return False
    return (datetime.now(timezone.utc) - ts) < ONLINE_THRESHOLD


def _now():
    return datetime.now(timezone.utc)


def get_rich_status(user_id: int) -> dict:
    """Return aggregated presence/status info for a user."""
    in_call    = _is_in_call(user_id)
    heartbeat  = _is_online_via_heartbeat(user_id)
    last_seen  = _get_last_seen(user_id) if _HAS_TRACKING else None

    if in_call:
        status = "in_call"
    elif heartbeat or last_seen:
        status = "online"
    else:
        status = "offline"

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
    # A user whose tabs are all closed can't be in a call, whatever stale rows say
    if not _is_online_via_heartbeat(user_id):
        return False
    try:
        return db.session.query(CommCallParticipant).join(CommCall).filter(
            CommCallParticipant.user_id  == user_id,
            CommCallParticipant.status   == "in_call",
            CommCall.status              == "active",
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
