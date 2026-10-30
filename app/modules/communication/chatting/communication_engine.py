"""
Façade that wires together all communication sub-services.
Import this class wherever you need to trigger communication actions from
other ERP modules (billing, HR, projects, etc.).
"""
from app.modules.communication.chatting import chat_service
from app.modules.communication.chatting import message_service
from app.modules.communication.chatting import ping_service
from app.modules.communication.chatting import notification_service
from app.modules.communication.chatting import voice_call_service
from app.modules.communication.chatting import meeting_service
from app.modules.communication.chatting import announcement_service
from app.modules.communication.chatting import presence_integration_service


class CommunicationEngine:

    # ── Chat ──────────────────────────────────────────────────────────────

    @staticmethod
    def send_direct_message(sender_id: int, receiver_id: int, content: str):
        conv = chat_service.get_or_create_direct_conversation(sender_id, receiver_id)
        return message_service.send_message(conv.id, sender_id, content=content)

    @staticmethod
    def open_context_thread(
        module:     str,
        record_id:  int,
        record_ref: str,
        opener_id:  int,
    ):
        return chat_service.get_or_create_context_conversation(
            module, record_id, record_ref, opener_id
        )

    # ── Pings ─────────────────────────────────────────────────────────────

    @staticmethod
    def send_ping(
        sender_id:          int,
        receiver_id:        int,
        ping_type:          str  = "ping",
        message:            str  = None,
        context_module:     str  = None,
        context_record_id:  int  = None,
        context_record_ref: str  = None,
    ):
        return ping_service.send_ping(
            sender_id          = sender_id,
            receiver_id        = receiver_id,
            ping_type          = ping_type,
            message            = message,
            context_module     = context_module,
            context_record_id  = context_record_id,
            context_record_ref = context_record_ref,
        )

    @staticmethod
    def send_approval_ping(
        sender_id:          int,
        receiver_id:        int,
        context_module:     str,
        context_record_id:  int,
        context_record_ref: str,
        message:            str = None,
    ):
        return ping_service.send_ping(
            sender_id          = sender_id,
            receiver_id        = receiver_id,
            ping_type          = "approval_request",
            message            = message,
            context_module     = context_module,
            context_record_id  = context_record_id,
            context_record_ref = context_record_ref,
        )

    # ── Calls ─────────────────────────────────────────────────────────────

    @staticmethod
    def start_voice_call(initiator_id: int, participant_ids: list):
        return voice_call_service.start_call(
            initiator_id    = initiator_id,
            participant_ids = participant_ids,
            call_type       = "voice",
        )

    @staticmethod
    def start_video_call(initiator_id: int, participant_ids: list):
        return voice_call_service.start_call(
            initiator_id    = initiator_id,
            participant_ids = participant_ids,
            call_type       = "video",
        )

    # ── Announcements ─────────────────────────────────────────────────────

    @staticmethod
    def broadcast_announcement(
        author_id:    int,
        title:        str,
        body:         str,
        audience_ids: list,
        priority:     str = "normal",
    ):
        return announcement_service.create_announcement(
            author_id    = author_id,
            title        = title,
            body         = body,
            audience_ids = audience_ids,
            priority     = priority,
        )

    # ── Directory ─────────────────────────────────────────────────────────

    @staticmethod
    def get_directory(requesting_user_id: int, search: str = None):
        return presence_integration_service.get_user_directory(
            requesting_user_id, search
        )

    # ── Notifications ─────────────────────────────────────────────────────

    @staticmethod
    def notify(
        user_id:           int,
        notification_type: str,
        title:             str,
        body:              str  = None,
        data:              dict = None,
    ):
        return notification_service.push_notification(
            user_id           = user_id,
            notification_type = notification_type,
            title             = title,
            body              = body,
            data              = data,
        )
