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
        .filter_by(conversation_id=conversation_id, status="active")
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


# ── Invites ──────────────────────────────────────────────────────────────────
# Any active member can invite people to a direct or group chat. Inviting into
# a direct chat turns it into a group, so the whole history carries over and
# the invitee sees all old messages once they accept.

def _display_name(conv, exclude_id=None):
    from app.models.user import User
    names = []
    for m in conv.members:
        if m.left_at or m.user_id == exclude_id:
            continue
        u = db.session.get(User, m.user_id)
        if u:
            names.append(u.username)
    return ", ".join(names[:4]) + ("…" if len(names) > 4 else "")


def invite_members(conversation_id: int, requester_id: int, user_ids: list, name: str = None):
    from app.models.user import User
    from app.modules.communication.chatting.notification_service import push_notification

    conv = db.session.get(CommConversation, conversation_id)
    req  = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=requester_id, status="active", left_at=None
    ).first()
    if not conv or not req or conv.conv_type not in ("direct", "group"):
        return None

    invited = []
    for uid in {int(u) for u in user_ids if u}:
        if uid == requester_id:
            continue
        m = CommConversationMember.query.filter_by(conversation_id=conversation_id, user_id=uid).first()
        if m and m.status == "active" and not m.left_at:
            continue  # already in
        if m:
            m.status, m.left_at, m.invited_by, m.joined_at = "invited", None, requester_id, _now()
        else:
            db.session.add(CommConversationMember(
                conversation_id=conversation_id, user_id=uid,
                role="member", status="invited", invited_by=requester_id,
            ))
        invited.append(uid)
    if not invited:
        return {"invited": [], "conversationId": conv.id, "type": conv.conv_type}

    if conv.conv_type == "direct":
        # Becomes a group; both original people stay admins
        conv.conv_type = "group"
        for m in conv.members:
            if m.status == "active" and not m.left_at:
                m.role = "admin"
        db.session.flush()
        conv.name = (name or "").strip() or _display_name(conv)
    elif name:
        conv.name = name.strip()
    db.session.commit()

    inviter = db.session.get(User, requester_id)
    for uid in invited:
        push_notification(
            user_id=uid, notification_type="chat_invite",
            title=f"{inviter.username if inviter else 'Someone'} invited you to {conv.name or 'a chat'}",
            data={"conversationId": conv.id},
        )
    return {"invited": invited, "conversationId": conv.id, "type": conv.conv_type}


def get_my_invites(user_id: int) -> list:
    from app.models.user import User
    rows = CommConversationMember.query.filter_by(user_id=user_id, status="invited", left_at=None).all()
    out = []
    for m in rows:
        conv = m.conversation
        if not conv or not conv.is_active:
            continue
        inviter = db.session.get(User, m.invited_by) if m.invited_by else None
        out.append({
            "conversationId": conv.id,
            "name":           conv.name or _display_name(conv, user_id),
            "invitedBy":      inviter.username if inviter else None,
            "memberCount":    sum(1 for x in conv.members if x.status == "active" and not x.left_at),
            "invitedAt":      m.joined_at.strftime("%Y-%m-%d %H:%M:%S") if m.joined_at else None,
        })
    return out


def respond_invite(conversation_id: int, user_id: int, accept: bool) -> bool:
    m = CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=user_id, status="invited"
    ).first()
    if not m:
        return False
    if accept:
        m.status, m.joined_at = "active", _now()
    else:
        m.left_at = _now()
    db.session.commit()
    return True
