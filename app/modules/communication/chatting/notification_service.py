import json
from datetime import datetime, timezone

from app.extensions import db
from app.models.communication_models import CommNotification


def _now():
    return datetime.now(timezone.utc)


def push_notification(
    user_id:           int,
    notification_type: str,
    title:             str,
    body:              str  = None,
    data:              dict = None,
) -> CommNotification:
    n = CommNotification(
        user_id           = user_id,
        notification_type = notification_type,
        title             = title,
        body              = body,
        data              = json.dumps(data) if data else None,
        created_at        = _now(),
    )
    db.session.add(n)
    db.session.commit()
    return n


def push_to_many(
    user_ids:          list,
    notification_type: str,
    title:             str,
    body:              str  = None,
    data:              dict = None,
) -> int:
    count = 0
    for uid in user_ids:
        push_notification(
            user_id=uid,
            notification_type=notification_type,
            title=title,
            body=body,
            data=data,
        )
        count += 1
    return count


def get_unread_notifications(user_id: int, limit: int = 50) -> dict:
    total = CommNotification.query.filter_by(user_id=user_id, is_read=False).count()
    rows  = (
        CommNotification.query
        .filter_by(user_id=user_id, is_read=False)
        .order_by(CommNotification.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "unreadCount": total,
        "items":       [_notif_dict(n) for n in rows],
    }


def get_all_notifications(user_id: int, limit: int = 50, offset: int = 0) -> dict:
    total = CommNotification.query.filter_by(user_id=user_id).count()
    rows  = (
        CommNotification.query
        .filter_by(user_id=user_id)
        .order_by(CommNotification.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return {
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "items":  [_notif_dict(n) for n in rows],
    }


def mark_notification_read(notification_id: int, user_id: int) -> bool:
    n = CommNotification.query.filter_by(id=notification_id, user_id=user_id).first()
    if not n:
        return False
    n.is_read = True
    n.read_at = _now()
    db.session.commit()
    return True


def mark_all_read(user_id: int) -> int:
    now  = _now()
    rows = CommNotification.query.filter_by(user_id=user_id, is_read=False).all()
    for n in rows:
        n.is_read = True
        n.read_at = now
    db.session.commit()
    return len(rows)


def _notif_dict(n: CommNotification) -> dict:
    return {
        "id":        n.id,
        "type":      n.notification_type,
        "title":     n.title,
        "body":      n.body,
        "data":      n.get_data(),
        "isRead":    n.is_read,
        "createdAt": n.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
