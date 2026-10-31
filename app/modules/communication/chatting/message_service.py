from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.communication_models import (
    CommMessage,
    CommMessageReceipt,
    CommConversationMember,
    CommTypingStatus,
)

TYPING_EXPIRE_SECONDS = 5


def _now():
    return datetime.now(timezone.utc)


def send_message(
    conversation_id: int,
    sender_id:       int,
    content:         str  = None,
    message_type:    str  = "text",
    file_url:        str  = None,
    file_name:       str  = None,
    file_size:       int  = None,
    file_mime:       str  = None,
    reply_to_id:     int  = None,
) -> CommMessage:
    from app.models.communication_models import CommConversation

    now = _now()
    msg = CommMessage(
        conversation_id = conversation_id,
        sender_id       = sender_id,
        message_type    = message_type,
        content         = content,
        file_url        = file_url,
        file_name       = file_name,
        file_size       = file_size,
        file_mime       = file_mime,
        reply_to_id     = reply_to_id,
        created_at      = now,
    )
    db.session.add(msg)

    conv = db.session.get(CommConversation, conversation_id)
    if conv:
        conv.updated_at = now

    db.session.commit()
    return msg


def get_message_history(
    conversation_id:    int,
    requesting_user_id: int,
    before_id:          int = None,
    limit:              int = 50,
) -> dict:
    query = CommMessage.query.filter_by(
        conversation_id = conversation_id,
        is_deleted      = False,
    )
    if before_id:
        query = query.filter(CommMessage.id < before_id)

    messages = (
        query
        .order_by(CommMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages = list(reversed(messages))

    _mark_delivered(messages, requesting_user_id)
    if messages:
        _update_last_read(conversation_id, requesting_user_id, messages[-1].id)

    return {
        "conversationId": conversation_id,
        "hasMore":        len(messages) == limit,
        "messages":       [_msg_dict(m, requesting_user_id) for m in messages],
    }


def get_new_messages(
    conversation_id:    int,
    requesting_user_id: int,
    after_id:           int = None,
) -> list:
    query = CommMessage.query.filter_by(
        conversation_id = conversation_id,
        is_deleted      = False,
    )
    if after_id:
        query = query.filter(CommMessage.id > after_id)

    messages = query.order_by(CommMessage.id.asc()).limit(100).all()

    _mark_delivered(messages, requesting_user_id)
    if messages:
        _update_last_read(conversation_id, requesting_user_id, messages[-1].id)

    return [_msg_dict(m, requesting_user_id) for m in messages]


def delete_message(message_id: int, requesting_user_id: int) -> bool:
    """Soft-delete. Only the sender can delete their own message."""
    msg = db.session.get(CommMessage, message_id)
    if not msg or msg.sender_id != requesting_user_id:
        return False
    msg.is_deleted = True
    msg.deleted_at = _now()
    db.session.commit()
    return True


def mark_message_read(message_id: int, user_id: int) -> None:
    receipt = CommMessageReceipt.query.filter_by(
        message_id=message_id, user_id=user_id
    ).first()
    if receipt:
        if receipt.status != "read":
            receipt.status     = "read"
            receipt.created_at = _now()
    else:
        db.session.add(CommMessageReceipt(
            message_id = message_id,
            user_id    = user_id,
            status     = "read",
        ))
    db.session.commit()


def set_typing(conversation_id: int, user_id: int) -> None:
    ts = CommTypingStatus.query.filter_by(
        conversation_id=conversation_id, user_id=user_id
    ).first()
    now = _now()
    if ts:
        ts.updated_at = now
    else:
        db.session.add(CommTypingStatus(
            conversation_id = conversation_id,
            user_id         = user_id,
            updated_at      = now,
        ))
    db.session.commit()


def get_typing_users(conversation_id: int, exclude_user_id: int) -> list:
    from app.models.user import User

    cutoff = _now() - timedelta(seconds=TYPING_EXPIRE_SECONDS)
    rows   = (
        db.session.query(CommTypingStatus, User)
        .join(User, User.id == CommTypingStatus.user_id)
        .filter(
            CommTypingStatus.conversation_id == conversation_id,
            CommTypingStatus.user_id         != exclude_user_id,
            CommTypingStatus.updated_at      >= cutoff,
        )
        .all()
    )
    return [{"userId": u.id, "userName": u.username} for ts, u in rows]


# ─── private helpers ──────────────────────────────────────────────────────────

def _mark_delivered(messages: list, user_id: int) -> None:
    for msg in messages:
        if msg.sender_id == user_id:
            continue
        exists = CommMessageReceipt.query.filter_by(
            message_id=msg.id, user_id=user_id
        ).first()
        if not exists:
            db.session.add(CommMessageReceipt(
                message_id = msg.id,
                user_id    = user_id,
                status     = "delivered",
            ))
    db.session.commit()


def _update_last_read(conversation_id: int, user_id: int, message_id: int) -> None:
    mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=user_id,
    ).first()
    if mem:
        mem.last_read_message_id = message_id
        db.session.commit()


def _reply_preview(msg: CommMessage) -> dict | None:
    parent = msg.reply_to
    if not parent:
        return None
    return {
        "id":         parent.id,
        "senderName": parent.sender.username if parent.sender else None,
        "type":       parent.message_type,
        "content":    None if parent.is_deleted else (parent.content or "")[:120],
        "fileName":   None if parent.is_deleted else parent.file_name,
        "isDeleted":  parent.is_deleted,
    }


def _msg_dict(msg: CommMessage, requesting_user_id: int) -> dict:
    receipts = {r.user_id: r.status for r in msg.receipts}
    return {
        "id":         msg.id,
        "senderId":   msg.sender_id,
        "senderName": msg.sender.username if msg.sender else None,
        "type":       msg.message_type,
        "content":    msg.content,
        "fileUrl":    msg.file_url,
        "fileName":   msg.file_name,
        "fileSize":   msg.file_size,
        "fileMime":   msg.file_mime,
        "replyToId":  msg.reply_to_id,
        "replyTo":    _reply_preview(msg),
        "isMine":     msg.sender_id == requesting_user_id,
        "receipts":   receipts,
        "isDeleted":  msg.is_deleted,
        "sentAt":     msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
