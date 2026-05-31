# app/models/communication_models.py
#
# All database models for the Internal Communication & Collaboration system.
# Completely independent — no changes to any existing model or table.
#
# Tables created:
#   comm_conversations          direct / group / context conversations
#   comm_conversation_members   membership + read position
#   comm_messages               chat messages (text / file / system)
#   comm_message_receipts       delivered + read receipts per user
#   comm_typing_status          real-time typing indicator (REST-polled)
#   comm_pings                  quick pings / nudges / attention requests
#   comm_notifications          per-user notification inbox
#   comm_calls                  voice + video call sessions
#   comm_call_participants      who is/was in each call
#   comm_call_signals           WebRTC signaling (offer/answer/ICE)
#   comm_meetings               conference + emergency meetings
#   comm_meeting_participants   attendance + invite status
#   comm_announcements          broadcast announcements
#   comm_announcement_reads     per-user read tracking

import json
from datetime import datetime
from app.extensions import db


# ═════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═════════════════════════════════════════════════════════════════════════════

class CommConversation(db.Model):
    """
    A conversation is a channel between 2+ users.
    type = "direct"  : 1-to-1 private chat
    type = "group"   : named group with multiple members
    type = "context" : discussion thread attached to an ERP record
    """
    __tablename__ = "comm_conversations"

    id          = db.Column(db.Integer, primary_key=True)
    type        = db.Column(db.String(20), nullable=False, default="direct")
                # "direct" | "group" | "context"

    # Group / context fields
    name        = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text,        nullable=True)
    avatar_url  = db.Column(db.String(500), nullable=True)

    # ERP context (for type="context")
    context_module     = db.Column(db.String(60),  nullable=True)
    context_record_id  = db.Column(db.Integer,      nullable=True)
    context_record_ref = db.Column(db.String(100),  nullable=True)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    creator  = db.relationship("User", foreign_keys=[created_by])
    members  = db.relationship(
        "CommConversationMember",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan"
    )
    messages = db.relationship(
        "CommMessage",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("ix_comm_conv_context", "context_module", "context_record_id"),
    )


class CommConversationMember(db.Model):
    """
    Membership record.  One row per (conversation, user) pair.
    last_read_message_id tracks what the user has seen (for unread count).
    """
    __tablename__ = "comm_conversation_members"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role               = db.Column(db.String(20), default="member")  # "admin" | "member"
    is_muted           = db.Column(db.Boolean, default=False)
    last_read_message_id = db.Column(db.Integer, nullable=True)
    joined_at          = db.Column(db.DateTime, default=datetime.utcnow)
    left_at            = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_comm_conv_member"
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# MESSAGES
# ═════════════════════════════════════════════════════════════════════════════

class CommMessage(db.Model):
    """
    A single message in a conversation.
    message_type:
      text    plain text
      file    file attachment (url stored separately)
      image   image attachment
      system  auto-generated system message (e.g. "Rohan joined")
      ping    inline ping inside a conversation
    """
    __tablename__ = "comm_messages"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    message_type = db.Column(db.String(20), nullable=False, default="text")
    content      = db.Column(db.Text,       nullable=True)

    # File attachment fields
    file_url  = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.Integer,     nullable=True)  # bytes
    file_mime = db.Column(db.String(100), nullable=True)

    # Thread / reply
    reply_to_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_messages.id", ondelete="SET NULL"),
        nullable=True
    )

    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    sender   = db.relationship("User", foreign_keys=[sender_id])
    reply_to = db.relationship("CommMessage", remote_side=[id])
    receipts = db.relationship(
        "CommMessageReceipt",
        backref="message",
        lazy=True,
        cascade="all, delete-orphan"
    )


class CommMessageReceipt(db.Model):
    """
    Read / delivered receipt per (message, user).
    status = "delivered" | "read"
    """
    __tablename__ = "comm_message_receipts"

    id         = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status     = db.Column(db.String(20), nullable=False)  # "delivered" | "read"
    created_at = db.Column(db.DateTime,  default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("message_id", "user_id", name="uq_comm_receipt"),
    )


class CommTypingStatus(db.Model):
    """
    Ephemeral typing indicator.
    Row expires (is ignored) if updated_at is older than 5 seconds.
    """
    __tablename__ = "comm_typing_status"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False
    )
    user_id    = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True
    )

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_comm_typing"
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# PINGS
# ═════════════════════════════════════════════════════════════════════════════

class CommPing(db.Model):
    """
    Quick ping / nudge / attention request.
    Can optionally reference an ERP record.
    """
    __tablename__ = "comm_pings"

    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # ping / nudge / attention / approval_request / urgent / review
    ping_type = db.Column(db.String(40), nullable=False, default="ping")
    message   = db.Column(db.String(500), nullable=True)

    # Optional ERP context
    context_module     = db.Column(db.String(60),  nullable=True)
    context_record_id  = db.Column(db.Integer,      nullable=True)
    context_record_ref = db.Column(db.String(100),  nullable=True)

    is_read    = db.Column(db.Boolean, default=False)
    read_at    = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    sender   = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

class CommNotification(db.Model):
    """
    Per-user notification inbox.
    notification_type:
      message | ping | call_incoming | call_missed | meeting_invite |
      announcement | approval_request | mention
    data: JSON string with type-specific payload (conversation_id, call_id, etc.)
    """
    __tablename__ = "comm_notifications"

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title             = db.Column(db.String(200), nullable=False)
    body              = db.Column(db.Text,        nullable=True)
    data              = db.Column(db.Text,        nullable=True)  # JSON

    is_read   = db.Column(db.Boolean, default=False, index=True)
    read_at   = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", foreign_keys=[user_id])

    def get_data(self) -> dict:
        """Deserialise the JSON data field."""
        try:
            return json.loads(self.data) if self.data else {}
        except (ValueError, TypeError):
            return {}


# ═════════════════════════════════════════════════════════════════════════════
# CALLS  (voice + video)
# ═════════════════════════════════════════════════════════════════════════════

class CommCall(db.Model):
    """
    A voice or video call session.
    room_code is the unique identifier used by the WebRTC layer.
    status: ringing → active → ended | missed | rejected
    """
    __tablename__ = "comm_calls"

    id           = db.Column(db.Integer, primary_key=True)
    call_type    = db.Column(db.String(20), nullable=False)  # "voice" | "video"
    initiator_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    room_code = db.Column(
        db.String(100),
        nullable=False,
        unique=True,
        index=True
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="ringing"
    )
    # "ringing" | "active" | "ended" | "missed" | "rejected"

    # Optional — links to a group conversation for group calls
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="SET NULL"),
        nullable=True
    )

    started_at       = db.Column(db.DateTime, nullable=True)
    ended_at         = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer,  nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    initiator    = db.relationship("User", foreign_keys=[initiator_id])
    participants = db.relationship(
        "CommCallParticipant",
        backref="call",
        lazy=True,
        cascade="all, delete-orphan"
    )
    signals = db.relationship(
        "CommCallSignal",
        backref="call",
        lazy=True,
        cascade="all, delete-orphan"
    )


class CommCallParticipant(db.Model):
    """
    One row per (call, user).
    status: invited → ringing → joined → left | rejected | missed
    """
    __tablename__ = "comm_call_participants"

    id      = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status = db.Column(db.String(20), nullable=False, default="invited")

    joined_at        = db.Column(db.DateTime, nullable=True)
    left_at          = db.Column(db.DateTime, nullable=True)
    is_muted         = db.Column(db.Boolean, default=False)
    has_video        = db.Column(db.Boolean, default=True)
    is_screen_sharing= db.Column(db.Boolean, default=False)

    user = db.relationship("User", foreign_keys=[user_id])


class CommCallSignal(db.Model):
    """
    WebRTC signaling messages stored for REST-polling exchange.
    signal_type: offer | answer | ice_candidate | reject | end | busy
    payload: JSON string (SDP or ICE candidate data)
    Signals are marked is_consumed=True after the recipient reads them.
    Auto-stale after 60 seconds (not enforced in DB, handled in service).
    """
    __tablename__ = "comm_call_signals"

    id           = db.Column(db.Integer, primary_key=True)
    call_id      = db.Column(
        db.Integer,
        db.ForeignKey("comm_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    from_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    to_user_id   = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    signal_type  = db.Column(db.String(30), nullable=False)
    payload      = db.Column(db.Text,       nullable=True)  # JSON
    is_consumed  = db.Column(db.Boolean, default=False, index=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    from_user = db.relationship("User", foreign_keys=[from_user_id])
    to_user   = db.relationship("User", foreign_keys=[to_user_id])


# ═════════════════════════════════════════════════════════════════════════════
# MEETINGS
# ═════════════════════════════════════════════════════════════════════════════

class CommMeeting(db.Model):
    """
    Conference / emergency meeting room.
    meeting_type: "conference" | "emergency"
    status: "scheduled" | "active" | "ended" | "cancelled"
    meeting_code is the unique room identifier (shareable link token).
    """
    __tablename__ = "comm_meetings"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text,        nullable=True)
    host_id      = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    meeting_code     = db.Column(db.String(50), nullable=False, unique=True, index=True)
    meeting_type     = db.Column(db.String(30), nullable=False, default="conference")
    status           = db.Column(db.String(20), nullable=False, default="scheduled")
    max_participants = db.Column(db.Integer, default=50)
    recording_url    = db.Column(db.String(500), nullable=True)

    scheduled_at = db.Column(db.DateTime, nullable=True)
    started_at   = db.Column(db.DateTime, nullable=True)
    ended_at     = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    host = db.relationship("User", foreign_keys=[host_id])
    participants = db.relationship(
        "CommMeetingParticipant",
        backref="meeting",
        lazy=True,
        cascade="all, delete-orphan"
    )


class CommMeetingParticipant(db.Model):
    """
    One row per (meeting, user).
    invite_status: invited | accepted | declined | joined | left
    """
    __tablename__ = "comm_meeting_participants"

    id         = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role          = db.Column(db.String(20), default="participant")  # "host" | "participant"
    invite_status = db.Column(db.String(20), default="invited")
    # "invited" | "accepted" | "declined" | "joined" | "left"

    joined_at  = db.Column(db.DateTime, nullable=True)
    left_at    = db.Column(db.DateTime, nullable=True)
    invited_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint("meeting_id", "user_id", name="uq_comm_meeting_participant"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS
# ═════════════════════════════════════════════════════════════════════════════

class CommAnnouncement(db.Model):
    """
    Broadcast announcement from Super Admin.
    announcement_type: "notice" | "alert" | "maintenance" | "policy"
    target_type: "all" | "role" | "specific_users"
    target_ids: JSON array of role IDs or user IDs (null = all)
    priority: "normal" | "high" | "urgent"
    """
    __tablename__ = "comm_announcements"

    id                = db.Column(db.Integer, primary_key=True)
    title             = db.Column(db.String(300), nullable=False)
    body              = db.Column(db.Text,         nullable=False)
    announcement_type = db.Column(db.String(30),   nullable=False, default="notice")
    priority          = db.Column(db.String(20),   nullable=False, default="normal")

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    target_type = db.Column(db.String(30), nullable=False, default="all")
    target_ids  = db.Column(db.Text, nullable=True)  # JSON array

    is_active  = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    reads   = db.relationship(
        "CommAnnouncementRead",
        backref="announcement",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def get_target_ids(self) -> list:
        try:
            return json.loads(self.target_ids) if self.target_ids else []
        except (ValueError, TypeError):
            return []


class CommAnnouncementRead(db.Model):
    """Track which users have seen each announcement."""
    __tablename__ = "comm_announcement_reads"

    id              = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id  = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    read_at  = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "announcement_id", "user_id",
            name="uq_comm_announcement_read"
        ),
    )


# =============================================================================
# INTEGRATION NOTE
# =============================================================================
# Existing file  : app/models/__init__.py
#
# Add at the bottom:
#
#   from .communication_models import (
#       CommConversation, CommConversationMember,
#       CommMessage, CommMessageReceipt, CommTypingStatus,
#       CommPing, CommNotification,
#       CommCall, CommCallParticipant, CommCallSignal,
#       CommMeeting, CommMeetingParticipant,
#       CommAnnouncement, CommAnnouncementRead,
#   )
#
# Then run:
#   flask db migrate -m "add communication tables"
#   flask db upgrade
# =============================================================================
