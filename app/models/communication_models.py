import json
from datetime import datetime, timezone
from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═════════════════════════════════════════════════════════════════════════════

class CommConversation(db.Model):
    __tablename__ = "comm_conversations"

    id          = db.Column(db.Integer, primary_key=True)
    conv_type   = db.Column("type", db.String(20), nullable=False, default="direct")
    # "direct" | "group" | "context"

    name        = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text,        nullable=True)
    avatar_url  = db.Column(db.String(500), nullable=True)

    context_module     = db.Column(db.String(60),  nullable=True)
    context_record_id  = db.Column(db.Integer,      nullable=True)
    context_record_ref = db.Column(db.String(100),  nullable=True)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=_now,
        onupdate=_now,
    )

    creator  = db.relationship("User", foreign_keys=[created_by])
    members  = db.relationship(
        "CommConversationMember",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan",
    )
    messages = db.relationship(
        "CommMessage",
        backref="conversation",
        lazy=True,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("ix_comm_conv_context", "context_module", "context_record_id"),
    )


class CommConversationMember(db.Model):
    __tablename__ = "comm_conversation_members"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role                 = db.Column(db.String(20), default="member")  # "admin" | "member"
    is_muted             = db.Column(db.Boolean, default=False)
    last_read_message_id = db.Column(db.Integer, nullable=True)
    joined_at            = db.Column(db.DateTime(timezone=True), default=_now)
    left_at              = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_comm_conv_member",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# MESSAGES
# ═════════════════════════════════════════════════════════════════════════════

class CommMessage(db.Model):
    __tablename__ = "comm_messages"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    message_type = db.Column(db.String(20), nullable=False, default="text")
    content      = db.Column(db.Text,       nullable=True)

    file_url  = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.Integer,     nullable=True)
    file_mime = db.Column(db.String(100), nullable=True)

    reply_to_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=_now,
        onupdate=_now,
    )

    sender   = db.relationship("User", foreign_keys=[sender_id])
    reply_to = db.relationship("CommMessage", remote_side="CommMessage.id")
    receipts = db.relationship(
        "CommMessageReceipt",
        backref="message",
        lazy=True,
        cascade="all, delete-orphan",
    )


class CommMessageReceipt(db.Model):
    __tablename__ = "comm_message_receipts"

    id         = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status     = db.Column(db.String(20), nullable=False)  # "delivered" | "read"
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    __table_args__ = (
        db.UniqueConstraint("message_id", "user_id", name="uq_comm_receipt"),
    )


class CommTypingStatus(db.Model):
    __tablename__ = "comm_typing_status"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id    = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        index=True,
    )

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_comm_typing",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# PINGS
# ═════════════════════════════════════════════════════════════════════════════

class CommPing(db.Model):
    __tablename__ = "comm_pings"

    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ping_type = db.Column(db.String(40), nullable=False, default="ping")
    message   = db.Column(db.String(500), nullable=True)

    context_module     = db.Column(db.String(60),  nullable=True)
    context_record_id  = db.Column(db.Integer,      nullable=True)
    context_record_ref = db.Column(db.String(100),  nullable=True)

    is_read    = db.Column(db.Boolean, default=False)
    read_at    = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    sender   = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

class CommNotification(db.Model):
    __tablename__ = "comm_notifications"

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title             = db.Column(db.String(200), nullable=False)
    body              = db.Column(db.Text,        nullable=True)
    data              = db.Column(db.Text,        nullable=True)  # JSON

    is_read    = db.Column(db.Boolean, default=False, index=True)
    read_at    = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    user = db.relationship("User", foreign_keys=[user_id])

    def get_data(self) -> dict:
        try:
            return json.loads(self.data) if self.data else {}
        except (ValueError, TypeError):
            return {}


# ═════════════════════════════════════════════════════════════════════════════
# CALLS  (voice + video)
# ═════════════════════════════════════════════════════════════════════════════

class CommCall(db.Model):
    __tablename__ = "comm_calls"

    id           = db.Column(db.Integer, primary_key=True)
    call_type    = db.Column(db.String(20), nullable=False)  # "voice" | "video"
    initiator_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    room_code = db.Column(
        db.String(100),
        nullable=False,
        unique=True,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default="ringing")
    # "ringing" | "active" | "ended" | "missed" | "rejected"

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    started_at       = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at         = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    created_at       = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    initiator    = db.relationship("User", foreign_keys=[initiator_id])
    participants = db.relationship(
        "CommCallParticipant",
        backref="call",
        lazy=True,
        cascade="all, delete-orphan",
    )
    signals = db.relationship(
        "CommCallSignal",
        backref="call",
        lazy=True,
        cascade="all, delete-orphan",
    )


class CommCallParticipant(db.Model):
    __tablename__ = "comm_call_participants"

    id      = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default="invited")

    joined_at         = db.Column(db.DateTime(timezone=True), nullable=True)
    left_at           = db.Column(db.DateTime(timezone=True), nullable=True)
    is_muted          = db.Column(db.Boolean, default=False)
    has_video         = db.Column(db.Boolean, default=True)
    is_screen_sharing = db.Column(db.Boolean, default=False)

    user = db.relationship("User", foreign_keys=[user_id])


class CommCallSignal(db.Model):
    __tablename__ = "comm_call_signals"

    id           = db.Column(db.Integer, primary_key=True)
    call_id      = db.Column(
        db.Integer,
        db.ForeignKey("comm_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id   = db.Column(db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    receiver_id = db.Column(db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_type = db.Column(db.String(30), nullable=False)
    payload     = db.Column(db.Text,       nullable=True)
    is_consumed = db.Column(db.Boolean, default=False, index=True)
    created_at  = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    sender   = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])


# ═════════════════════════════════════════════════════════════════════════════
# MEETINGS
# ═════════════════════════════════════════════════════════════════════════════

class CommMeeting(db.Model):
    __tablename__ = "comm_meetings"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text,        nullable=True)
    host_id      = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    meeting_code     = db.Column(db.String(50), nullable=False, unique=True, index=True)
    meeting_type     = db.Column(db.String(30), nullable=False, default="conference")
    status           = db.Column(db.String(20), nullable=False, default="scheduled")
    max_participants = db.Column(db.Integer, default=50)
    recording_url    = db.Column(db.String(500), nullable=True)

    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    started_at   = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at     = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at   = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    host         = db.relationship("User", foreign_keys=[host_id])
    participants = db.relationship(
        "CommMeetingParticipant",
        backref="meeting",
        lazy=True,
        cascade="all, delete-orphan",
    )


class CommMeetingParticipant(db.Model):
    __tablename__ = "comm_meeting_participants"

    id         = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role          = db.Column(db.String(20), default="participant")
    invite_status = db.Column(db.String(20), default="invited")
    # "invited" | "accepted" | "declined" | "joined" | "left"

    joined_at  = db.Column(db.DateTime(timezone=True), nullable=True)
    left_at    = db.Column(db.DateTime(timezone=True), nullable=True)
    invited_at = db.Column(db.DateTime(timezone=True), default=_now)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint("meeting_id", "user_id", name="uq_comm_meeting_participant"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS
# ═════════════════════════════════════════════════════════════════════════════

class CommAnnouncement(db.Model):
    __tablename__ = "comm_announcements"

    id                = db.Column(db.Integer, primary_key=True)
    title             = db.Column(db.String(300), nullable=False)
    body              = db.Column(db.Text,         nullable=False)
    announcement_type = db.Column(db.String(30),   nullable=False, default="notice")
    priority          = db.Column(db.String(20),   nullable=False, default="normal")

    created_by  = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_type = db.Column(db.String(30), nullable=False, default="all")
    target_ids  = db.Column(db.Text, nullable=True)  # JSON array

    is_active  = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    reads   = db.relationship(
        "CommAnnouncementRead",
        backref="announcement",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def get_target_ids(self) -> list:
        try:
            return json.loads(self.target_ids) if self.target_ids else []
        except (ValueError, TypeError):
            return []


class CommAnnouncementRead(db.Model):
    __tablename__ = "comm_announcement_reads"

    id              = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(
        db.Integer,
        db.ForeignKey("comm_announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at = db.Column(db.DateTime(timezone=True), default=_now)

    __table_args__ = (
        db.UniqueConstraint(
            "announcement_id", "user_id",
            name="uq_comm_announcement_read",
        ),
    )
