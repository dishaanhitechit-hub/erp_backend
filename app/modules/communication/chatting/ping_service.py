from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import CommPing
from app.modules.communication.chatting.notification_service import push_notification

PING_TYPES = {
    "ping":             "Ping",
    "nudge":            "Nudge",
    "attention":        "Attention Required",
    "approval_request": "Approval Requested",
    "urgent":           "URGENT",
    "review":           "Need Review",
    "check":            "Please Check",
}


def _now():
    return datetime.now(timezone.utc)


def send_ping(
    sender_id:         int,
    receiver_id:       int,
    ping_type:         str  = "ping",
    message:           str  = None,
    context_module:    str  = None,
    context_record_id: int  = None,
    context_record_ref:str  = None,
) -> CommPing:
    from app.models.user import User

    ping = CommPing(
        sender_id          = sender_id,
        receiver_id        = receiver_id,
        ping_type          = ping_type,
        message            = message,
        context_module     = context_module,
        context_record_id  = context_record_id,
        context_record_ref = context_record_ref,
        created_at         = _now(),
    )
    db.session.add(ping)
    db.session.commit()

    sender      = db.session.get(User, sender_id)
    sender_name = sender.username if sender else "Someone"
    ping_label  = PING_TYPES.get(ping_type, "Ping")

    push_notification(
        user_id           = receiver_id,
        notification_type = "ping",
        title             = f"{ping_label} from {sender_name}",
        body              = message or (
            f"Regarding {context_record_ref}" if context_record_ref else None
        ),
        data              = {
            "pingId":          ping.id,
            "pingType":        ping_type,
            "senderId":        sender_id,
            "senderName":      sender_name,
            "contextModule":   context_module,
            "contextRecordId": context_record_id,
            "contextRecordRef":context_record_ref,
        },
    )
    return ping


def get_received_pings(user_id: int, unread_only: bool = False, limit: int = 50) -> list:
    query = CommPing.query.filter_by(receiver_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    pings = query.order_by(CommPing.created_at.desc()).limit(limit).all()
    return [_ping_dict(p) for p in pings]


def get_sent_pings(user_id: int, limit: int = 50) -> list:
    pings = (
        CommPing.query
        .filter_by(sender_id=user_id)
        .order_by(CommPing.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_ping_dict(p) for p in pings]


def mark_ping_read(ping_id: int, user_id: int) -> bool:
    ping = CommPing.query.filter_by(id=ping_id, receiver_id=user_id).first()
    if not ping:
        return False
    ping.is_read = True
    ping.read_at = _now()
    db.session.commit()
    return True


def get_unread_ping_count(user_id: int) -> int:
    return CommPing.query.filter_by(receiver_id=user_id, is_read=False).count()


def _ping_dict(ping: CommPing) -> dict:
    return {
        "id":               ping.id,
        "senderId":         ping.sender_id,
        "senderName":       ping.sender.username   if ping.sender   else None,
        "receiverId":       ping.receiver_id,
        "receiverName":     ping.receiver.username if ping.receiver else None,
        "pingType":         ping.ping_type,
        "pingLabel":        PING_TYPES.get(ping.ping_type, ping.ping_type),
        "message":          ping.message,
        "contextModule":    ping.context_module,
        "contextRecordId":  ping.context_record_id,
        "contextRecordRef": ping.context_record_ref,
        "isRead":           ping.is_read,
        "createdAt":        ping.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
