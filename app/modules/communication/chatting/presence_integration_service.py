from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.communication_models import CommCall, CommCallParticipant

try:
    from app.modules.hr.employee_tracking.tracking_service import get_user_last_seen
    _HAS_TRACKING = True
except ImportError:
    _HAS_TRACKING = False

import os

from app.models.communication_models import CommPresence

# How long a check-in keeps someone "online".
#  web / app open: they check in every ~45 s, so a short window.
#  app in background: the phone checks in about every 15 min (Android's limit)
#  and can still be reached by push, so they stay online a little longer.
ONLINE_THRESHOLD = timedelta(seconds=90)
BACKGROUND_THRESHOLD = timedelta(minutes=int(os.getenv("PRESENCE_BG_MINUTES") or 20))
_SOURCES = ("web", "app", "app_bg")

# Small fallback cache if the database can't be read.
_cache: dict = {}   # user_id → (fg_seen_at, bg_seen_at, source)


def record_heartbeat(user_id: int, source: str = "web") -> None:
    source = source if source in _SOURCES else "web"
    now = datetime.now(timezone.utc)
    try:
        row = db.session.get(CommPresence, user_id)
        if row is None:
            row = CommPresence(user_id=user_id)
            db.session.add(row)
        row.last_seen_at = now
        row.source = source
        if source == "app_bg":
            row.bg_seen_at = now
        else:
            row.fg_seen_at = now
        db.session.commit()
        _cache[user_id] = (_aware(row.fg_seen_at), _aware(row.bg_seen_at), row.source)
    except Exception:
        db.session.rollback()
        old = _cache.get(user_id, (None, None, source))
        _cache[user_id] = (old[0], now, source) if source == "app_bg" else (now, old[1], source)


def _aware(ts):
    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _presence_rows(user_ids):
    """{user_id: (fg_seen_at, bg_seen_at, source)} for these users (one query)."""
    ids = [int(u) for u in user_ids if u]
    if not ids:
        return {}
    try:
        rows = CommPresence.query.filter(CommPresence.user_id.in_(ids)).all()
        return {r.user_id: (_aware(r.fg_seen_at), _aware(r.bg_seen_at), r.source) for r in rows}
    except Exception:
        db.session.rollback()
        return {u: _cache[u] for u in ids if u in _cache}


def _online(entry) -> bool:
    if not entry:
        return False
    fg, bg, _ = entry
    now = datetime.now(timezone.utc)
    return bool((fg and now - fg < ONLINE_THRESHOLD) or (bg and now - bg < BACKGROUND_THRESHOLD))


def _last_seen(entry):
    if not entry:
        return None
    times = [t for t in entry[:2] if t]
    return max(times) if times else None


def _is_online_via_heartbeat(user_id: int) -> bool:
    return _online(_presence_rows([user_id]).get(user_id))


def get_rich_status(user_id: int, presence=None) -> dict:
    """Return aggregated presence/status info for a user.
    [presence]: this user's (last_seen_at, source), when already loaded."""
    entry = presence if presence is not None else _presence_rows([user_id]).get(user_id)
    heartbeat  = _online(entry)
    in_call    = heartbeat and _is_in_call(user_id, checked_online=True)
    last_seen  = _get_last_seen(user_id) if _HAS_TRACKING else None
    if last_seen is None and _last_seen(entry):
        last_seen = _last_seen(entry).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")

    if in_call:
        status = "in_call"
    elif heartbeat:
        status = "online"
    else:
        status = "offline"

    return {
        "userId":   user_id,
        "status":   status,
        "inCall":   in_call,
        "lastSeen": last_seen,
        "onApp":    bool(entry and entry[2] in ("app", "app_bg")),
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
    presence = _presence_rows([u.id for u in users])   # one query for everyone
    return [
        {
            "userId":   u.id,
            "userName": u.username,
            "empCode":  u.emp_code,
            **get_rich_status(u.id, presence.get(u.id, ())),
        }
        for u in users
        if u.id != requesting_user_id
    ]


def set_communication_status(user_id: int, status: str) -> bool:
    """Placeholder — update status if a custom status model is added later."""
    return True


def _is_in_call(user_id: int, checked_online: bool = False) -> bool:
    # A user whose tabs are all closed can't be in a call, whatever stale rows say
    if not checked_online and not _is_online_via_heartbeat(user_id):
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
