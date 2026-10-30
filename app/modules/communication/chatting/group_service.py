from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import CommConversation, CommConversationMember


def _now():
    return datetime.now(timezone.utc)


def add_member(
    conversation_id:  int,
    requester_id:     int,
    new_user_id:      int,
) -> bool:
    """Add a user to a group. Only admins can do this."""
    requester_mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=requester_id
    ).first()
    if not requester_mem or requester_mem.role != "admin":
        return False

    existing = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=new_user_id
    ).first()
    if existing:
        if existing.left_at:
            existing.left_at = None
            db.session.commit()
        return True

    db.session.add(CommConversationMember(
        conversation_id = conversation_id,
        user_id         = new_user_id,
        role            = "member",
    ))
    db.session.commit()
    return True


def remove_member(
    conversation_id: int,
    requester_id:    int,
    target_user_id:  int,
) -> bool:
    """Remove a user from a group. Admins can remove anyone; members can only remove themselves."""
    requester_mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=requester_id
    ).first()
    if not requester_mem:
        return False

    if requester_id != target_user_id and requester_mem.role != "admin":
        return False

    target_mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=target_user_id
    ).first()
    if not target_mem:
        return False

    target_mem.left_at = _now()
    db.session.commit()
    return True


def promote_admin(
    conversation_id: int,
    requester_id:    int,
    target_user_id:  int,
) -> bool:
    """Promote a member to admin. Only existing admins can do this."""
    requester_mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=requester_id
    ).first()
    if not requester_mem or requester_mem.role != "admin":
        return False

    target_mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=target_user_id
    ).first()
    if not target_mem:
        return False

    target_mem.role = "admin"
    db.session.commit()
    return True


def get_group_members(conversation_id: int) -> list:
    from app.models.user import User

    members = (
        CommConversationMember.query
        .filter_by(conversation_id=conversation_id)
        .filter(CommConversationMember.left_at == None)
        .all()
    )
    result = []
    for m in members:
        u = db.session.get(User, m.user_id)
        if u:
            result.append({
                "userId":   u.id,
                "userName": u.username,
                "empCode":  u.emp_code,
                "role":     m.role,
                "isMuted":  m.is_muted,
                "joinedAt": m.joined_at.strftime("%Y-%m-%d %H:%M:%S") if m.joined_at else None,
            })
    return result


def update_group_info(
    conversation_id: int,
    requester_id:    int,
    name:            str = None,
    description:     str = None,
) -> bool:
    """Only admins can update group info."""
    mem = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=requester_id
    ).first()
    if not mem or mem.role != "admin":
        return False

    conv = db.session.get(CommConversation, conversation_id)
    if not conv:
        return False

    if name is not None:
        conv.name = name
    if description is not None:
        conv.description = description

    db.session.commit()
    return True
