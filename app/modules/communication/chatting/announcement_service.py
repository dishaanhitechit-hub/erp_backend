from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import CommAnnouncement, CommAnnouncementRead
from app.modules.communication.chatting.notification_service import push_to_many


def _now():
    return datetime.now(timezone.utc)


def create_announcement(
    author_id:    int,
    title:        str,
    body:         str,
    audience_ids: list,
    priority:     str = "normal",
    expires_at:   datetime = None,
) -> CommAnnouncement:
    announcement = CommAnnouncement(
        author_id  = author_id,
        title      = title,
        body       = body,
        priority   = priority,
        expires_at = expires_at,
        created_at = _now(),
    )
    db.session.add(announcement)
    db.session.commit()

    push_to_many(
        user_ids          = audience_ids,
        notification_type = "announcement",
        title             = f"[Announcement] {title}",
        body              = body[:200] if len(body) > 200 else body,
        data              = {
            "announcementId": announcement.id,
            "priority":       priority,
        },
    )
    return announcement


def get_active_announcements(user_id: int) -> list:
    now   = _now()
    rows  = (
        CommAnnouncement.query
        .filter(
            CommAnnouncement.is_active == True,
            db.or_(
                CommAnnouncement.expires_at == None,
                CommAnnouncement.expires_at > now,
            ),
        )
        .order_by(CommAnnouncement.created_at.desc())
        .all()
    )
    read_ids = {
        r.announcement_id
        for r in CommAnnouncementRead.query.filter_by(user_id=user_id).all()
    }
    return [_ann_dict(a, a.id in read_ids) for a in rows]


def get_all_announcements(limit: int = 50, offset: int = 0) -> list:
    rows = (
        CommAnnouncement.query
        .order_by(CommAnnouncement.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_ann_dict(a) for a in rows]


def mark_announcement_read(announcement_id: int, user_id: int) -> bool:
    existing = CommAnnouncementRead.query.filter_by(
        announcement_id=announcement_id, user_id=user_id
    ).first()
    if existing:
        return True

    db.session.add(CommAnnouncementRead(
        announcement_id = announcement_id,
        user_id         = user_id,
        read_at         = _now(),
    ))
    db.session.commit()
    return True


def deactivate_announcement(announcement_id: int, requester_id: int) -> bool:
    ann = db.session.get(CommAnnouncement, announcement_id)
    if not ann or ann.author_id != requester_id:
        return False
    ann.is_active = False
    db.session.commit()
    return True


def _ann_dict(ann: CommAnnouncement, is_read: bool = False) -> dict:
    return {
        "id":        ann.id,
        "authorId":  ann.author_id,
        "title":     ann.title,
        "body":      ann.body,
        "priority":  ann.priority,
        "isActive":  ann.is_active,
        "isRead":    is_read,
        "expiresAt": ann.expires_at.strftime("%Y-%m-%d %H:%M:%S") if ann.expires_at else None,
        "createdAt": ann.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
