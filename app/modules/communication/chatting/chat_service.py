from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import (
    CommConversation,
    CommConversationMember,
    CommMessage,
)


def _now():
    return datetime.now(timezone.utc)


def get_or_create_direct_conversation(user_a_id: int, user_b_id: int) -> CommConversation:
    """Return existing direct conversation between two users, or create one."""
    conv_ids_a = {
        m.conversation_id
        for m in CommConversationMember.query.filter_by(user_id=user_a_id).all()
    }
    conv_ids_b = {
        m.conversation_id
        for m in CommConversationMember.query.filter_by(user_id=user_b_id).all()
    }
    shared = conv_ids_a & conv_ids_b

    if shared:
        existing = (
            CommConversation.query
            .filter(
                CommConversation.id.in_(shared),
                CommConversation.conv_type == "direct",
            )
            .first()
        )
        if existing:
            return existing

    conv = CommConversation(
        conv_type  = "direct",
        created_by = user_a_id,
    )
    db.session.add(conv)
    db.session.flush()

    for uid in (user_a_id, user_b_id):
        db.session.add(CommConversationMember(
            conversation_id = conv.id,
            user_id         = uid,
            role            = "member",
        ))

    db.session.commit()
    return conv


def create_group_conversation(
    creator_id:  int,
    name:        str,
    member_ids:  list,
    description: str = None,
) -> CommConversation:
    """Create a named group conversation. Creator is automatically admin."""
    conv = CommConversation(
        conv_type   = "group",
        name        = name,
        description = description,
        created_by  = creator_id,
    )
    db.session.add(conv)
    db.session.flush()

    db.session.add(CommConversationMember(
        conversation_id = conv.id,
        user_id         = creator_id,
        role            = "admin",
    ))

    for uid in member_ids:
        if uid != creator_id:
            db.session.add(CommConversationMember(
                conversation_id = conv.id,
                user_id         = uid,
                role            = "member",
            ))

    db.session.commit()
    return conv


def get_or_create_context_conversation(
    module:     str,
    record_id:  int,
    record_ref: str,
    opener_id:  int,
) -> CommConversation:
    """Return (or create) the discussion thread attached to an ERP record."""
    conv = CommConversation.query.filter_by(
        conv_type         = "context",
        context_module    = module,
        context_record_id = record_id,
    ).first()

    if not conv:
        conv = CommConversation(
            conv_type          = "context",
            name               = f"{module.upper()} - {record_ref}",
            context_module     = module,
            context_record_id  = record_id,
            context_record_ref = record_ref,
            created_by         = opener_id,
        )
        db.session.add(conv)
        db.session.flush()

    existing = CommConversationMember.query.filter_by(
        conversation_id = conv.id,
        user_id         = opener_id,
    ).first()
    if not existing:
        db.session.add(CommConversationMember(
            conversation_id = conv.id,
            user_id         = opener_id,
            role            = "member",
        ))

    db.session.commit()
    return conv


def get_user_conversations(user_id: int) -> list:
    """Return all active conversations for a user, sorted by most recent message."""
    from app.models.user import User

    memberships = (
        CommConversationMember.query
        .filter_by(user_id=user_id)
        .filter(CommConversationMember.left_at == None)
        .all()
    )

    result = []
    for mem in memberships:
        conv = mem.conversation
        if not conv or not conv.is_active:
            continue

        # Unread count: messages newer than last_read_message_id that weren't sent by me
        unread_query = CommMessage.query.filter(
            CommMessage.conversation_id == conv.id,
            CommMessage.is_deleted == False,
            CommMessage.sender_id != user_id,
        )
        if mem.last_read_message_id:
            unread_query = unread_query.filter(
                CommMessage.id > mem.last_read_message_id
            )
        unread = unread_query.count()

        last_msg = (
            CommMessage.query
            .filter_by(conversation_id=conv.id, is_deleted=False)
            .order_by(CommMessage.created_at.desc())
            .first()
        )

        other_user = None
        if conv.conv_type == "direct":
            other_mem = CommConversationMember.query.filter(
                CommConversationMember.conversation_id == conv.id,
                CommConversationMember.user_id != user_id,
            ).first()
            if other_mem:
                other_user = db.session.get(User, other_mem.user_id)

        result.append({
            "conversationId":   conv.id,
            "type":             conv.conv_type,
            "name": (
                conv.name
                if conv.conv_type in ("group", "context")
                else (other_user.username if other_user else "Unknown")
            ),
            "contextModule":    conv.context_module,
            "contextRecordRef": conv.context_record_ref,
            "unreadCount":      unread,
            "isMuted":          mem.is_muted,
            "lastMessage": {
                "content":    last_msg.content if last_msg else None,
                "sentAt":     last_msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if last_msg else None,
                "senderName": (last_msg.sender.username if last_msg and last_msg.sender else None),
            } if last_msg else None,
            "otherUser": {
                "id":       other_user.id,
                "userName": other_user.username,
                "empCode":  other_user.emp_code,
            } if other_user else None,
            "updatedAt": conv.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    result.sort(
        key=lambda x: x["lastMessage"]["sentAt"] if x["lastMessage"] else "0",
        reverse=True,
    )
    return result


def get_conversation_detail(conversation_id: int, requesting_user_id: int) -> dict | None:
    """Return conversation detail including member list."""
    from app.models.user import User

    conv = db.session.get(CommConversation, conversation_id)
    if not conv:
        return None

    mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=requesting_user_id,
    ).first()
    if not mem:
        return None

    members = []
    for m in conv.members:
        if m.left_at:
            continue
        u = db.session.get(User, m.user_id)
        if u:
            members.append({
                "userId":   u.id,
                "userName": u.username,
                "empCode":  u.emp_code,
                "role":     m.role,
                "isMuted":  m.is_muted,
            })

    return {
        "conversationId":   conv.id,
        "type":             conv.conv_type,
        "name":             conv.name,
        "description":      conv.description,
        "contextModule":    conv.context_module,
        "contextRecordId":  conv.context_record_id,
        "contextRecordRef": conv.context_record_ref,
        "members":          members,
        "memberCount":      len(members),
        "myRole":           mem.role,
        "isMuted":          mem.is_muted,
        "createdAt":        conv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def mute_conversation(conversation_id: int, user_id: int, mute: bool) -> bool:
    mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=user_id,
    ).first()
    if not mem:
        return False
    mem.is_muted = mute
    db.session.commit()
    return True


def leave_conversation(conversation_id: int, user_id: int) -> bool:
    mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id,
        user_id=user_id,
    ).first()
    if not mem:
        return False
    mem.left_at = _now()
    db.session.commit()
    return True
