from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.communication.chatting import chat_service
from app.modules.communication.chatting import message_service
from app.modules.communication.chatting import ping_service
from app.modules.communication.chatting import notification_service
from app.modules.communication.chatting import voice_call_service
from app.modules.communication.chatting import group_service
from app.modules.communication.chatting import meeting_service
from app.modules.communication.chatting import announcement_service
from app.modules.communication.chatting import presence_integration_service

comm_bp = Blueprint("comm", __name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/conversations", methods=["GET"])
@jwt_required()
def list_conversations():
    user_id = int(get_jwt_identity())
    try:
        return jsonify(chat_service.get_user_conversations(user_id)), 200
    except Exception:
        return jsonify([]), 200


@comm_bp.route("/conversations/direct", methods=["POST"])
@jwt_required()
def start_direct():
    user_id    = int(get_jwt_identity())
    other_id   = request.json.get("userId")
    if not other_id:
        return jsonify({"error": "userId required"}), 400
    conv = chat_service.get_or_create_direct_conversation(user_id, int(other_id))
    return jsonify({"conversationId": conv.id}), 200


@comm_bp.route("/conversations/group", methods=["POST"])
@jwt_required()
def create_group():
    user_id     = int(get_jwt_identity())
    data        = request.json
    name        = data.get("name")
    member_ids  = data.get("memberIds", [])
    description = data.get("description")
    if not name:
        return jsonify({"error": "name required"}), 400
    conv = chat_service.create_group_conversation(
        creator_id  = user_id,
        name        = name,
        member_ids  = member_ids,
        description = description,
    )
    return jsonify({"conversationId": conv.id}), 201


@comm_bp.route("/conversations/context", methods=["POST"])
@jwt_required()
def open_context():
    user_id    = int(get_jwt_identity())
    data       = request.json
    module     = data.get("module")
    record_id  = data.get("recordId")
    record_ref = data.get("recordRef", "")
    if not module or not record_id:
        return jsonify({"error": "module and recordId required"}), 400
    conv = chat_service.get_or_create_context_conversation(
        module     = module,
        record_id  = int(record_id),
        record_ref = record_ref,
        opener_id  = user_id,
    )
    return jsonify({"conversationId": conv.id}), 200


@comm_bp.route("/conversations/<int:conv_id>", methods=["GET"])
@jwt_required()
def conversation_detail(conv_id):
    user_id = int(get_jwt_identity())
    detail  = chat_service.get_conversation_detail(conv_id, user_id)
    if not detail:
        return jsonify({"error": "Not found or not a member"}), 404
    return jsonify(detail), 200


@comm_bp.route("/conversations/<int:conv_id>/mute", methods=["POST"])
@jwt_required()
def mute_conversation(conv_id):
    user_id = int(get_jwt_identity())
    mute    = request.json.get("mute", True)
    ok      = chat_service.mute_conversation(conv_id, user_id, bool(mute))
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/conversations/<int:conv_id>/leave", methods=["POST"])
@jwt_required()
def leave_conversation(conv_id):
    user_id = int(get_jwt_identity())
    ok      = chat_service.leave_conversation(conv_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/conversations/<int:conv_id>/messages", methods=["GET"])
@jwt_required()
def get_messages(conv_id):
    user_id   = int(get_jwt_identity())
    before_id = request.args.get("beforeId", type=int)
    limit     = request.args.get("limit", 50, type=int)
    return jsonify(
        message_service.get_message_history(conv_id, user_id, before_id, limit)
    ), 200


@comm_bp.route("/conversations/<int:conv_id>/messages/new", methods=["GET"])
@jwt_required()
def get_new_messages(conv_id):
    user_id  = int(get_jwt_identity())
    after_id = request.args.get("afterId", type=int)
    return jsonify(
        message_service.get_new_messages(conv_id, user_id, after_id)
    ), 200


@comm_bp.route("/conversations/<int:conv_id>/messages", methods=["POST"])
@jwt_required()
def send_message(conv_id):
    user_id = int(get_jwt_identity())
    data    = request.json
    msg = message_service.send_message(
        conversation_id = conv_id,
        sender_id       = user_id,
        content         = data.get("content"),
        message_type    = data.get("type", "text"),
        file_url        = data.get("fileUrl"),
        file_name       = data.get("fileName"),
        file_size       = data.get("fileSize"),
        file_mime       = data.get("fileMime"),
        reply_to_id     = data.get("replyToId"),
    )
    return jsonify({"messageId": msg.id}), 201


@comm_bp.route("/messages/<int:msg_id>", methods=["DELETE"])
@jwt_required()
def delete_message(msg_id):
    user_id = int(get_jwt_identity())
    ok      = message_service.delete_message(msg_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found or not yours"}), 404)


@comm_bp.route("/messages/<int:msg_id>/read", methods=["POST"])
@jwt_required()
def mark_read(msg_id):
    user_id = int(get_jwt_identity())
    message_service.mark_message_read(msg_id, user_id)
    return jsonify({"ok": True}), 200


@comm_bp.route("/conversations/<int:conv_id>/typing", methods=["POST"])
@jwt_required()
def set_typing(conv_id):
    user_id = int(get_jwt_identity())
    message_service.set_typing(conv_id, user_id)
    return jsonify({"ok": True}), 200


@comm_bp.route("/conversations/<int:conv_id>/typing", methods=["GET"])
@jwt_required()
def get_typing(conv_id):
    user_id = int(get_jwt_identity())
    return jsonify(
        message_service.get_typing_users(conv_id, user_id)
    ), 200


# ══════════════════════════════════════════════════════════════════════════════
# GROUP MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/conversations/<int:conv_id>/members", methods=["GET"])
@jwt_required()
def group_members(conv_id):
    return jsonify(group_service.get_group_members(conv_id)), 200


@comm_bp.route("/conversations/<int:conv_id>/members", methods=["POST"])
@jwt_required()
def add_member(conv_id):
    user_id    = int(get_jwt_identity())
    new_uid    = request.json.get("userId")
    ok         = group_service.add_member(conv_id, user_id, int(new_uid))
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


@comm_bp.route("/conversations/<int:conv_id>/members/<int:target_id>", methods=["DELETE"])
@jwt_required()
def remove_member(conv_id, target_id):
    user_id = int(get_jwt_identity())
    ok      = group_service.remove_member(conv_id, user_id, target_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


@comm_bp.route("/conversations/<int:conv_id>/members/<int:target_id>/promote", methods=["POST"])
@jwt_required()
def promote_member(conv_id, target_id):
    user_id = int(get_jwt_identity())
    ok      = group_service.promote_admin(conv_id, user_id, target_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


@comm_bp.route("/conversations/<int:conv_id>/info", methods=["PATCH"])
@jwt_required()
def update_group_info(conv_id):
    user_id     = int(get_jwt_identity())
    data        = request.json
    ok = group_service.update_group_info(
        conv_id, user_id,
        name        = data.get("name"),
        description = data.get("description"),
    )
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


# ══════════════════════════════════════════════════════════════════════════════
# PINGS / NUDGES
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/pings", methods=["POST"])
@jwt_required()
def send_ping():
    user_id = int(get_jwt_identity())
    data    = request.json
    target  = data.get("receiverId")
    if not target:
        return jsonify({"error": "receiverId required"}), 400
    ping = ping_service.send_ping(
        sender_id          = user_id,
        receiver_id        = int(target),
        ping_type          = data.get("pingType", "ping"),
        message            = data.get("message"),
        context_module     = data.get("contextModule"),
        context_record_id  = data.get("contextRecordId"),
        context_record_ref = data.get("contextRecordRef"),
    )
    return jsonify({"pingId": ping.id}), 201


@comm_bp.route("/pings/received", methods=["GET"])
@jwt_required()
def received_pings():
    user_id     = int(get_jwt_identity())
    unread_only = request.args.get("unreadOnly", "false").lower() == "true"
    return jsonify(ping_service.get_received_pings(user_id, unread_only)), 200


@comm_bp.route("/pings/sent", methods=["GET"])
@jwt_required()
def sent_pings():
    user_id = int(get_jwt_identity())
    return jsonify(ping_service.get_sent_pings(user_id)), 200


@comm_bp.route("/pings/<int:ping_id>/read", methods=["POST"])
@jwt_required()
def mark_ping_read(ping_id):
    user_id = int(get_jwt_identity())
    ok      = ping_service.mark_ping_read(ping_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/pings/read-all", methods=["POST"])
@jwt_required()
def mark_all_pings_read():
    user_id = int(get_jwt_identity())
    return jsonify({"marked": ping_service.mark_all_pings_read(user_id)}), 200


@comm_bp.route("/pings/unread-count", methods=["GET"])
@jwt_required()
def unread_ping_count():
    user_id = int(get_jwt_identity())
    try:
        return jsonify({"count": ping_service.get_unread_ping_count(user_id)}), 200
    except Exception:
        return jsonify({"count": 0}), 200


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/notifications", methods=["GET"])
@jwt_required()
def list_notifications():
    user_id     = int(get_jwt_identity())
    unread_only = request.args.get("unreadOnly", "false").lower() == "true"
    limit       = request.args.get("limit", 50, type=int)
    offset      = request.args.get("offset", 0, type=int)
    try:
        if unread_only:
            return jsonify(notification_service.get_unread_notifications(user_id, limit)), 200
        return jsonify(notification_service.get_all_notifications(user_id, limit, offset)), 200
    except Exception:
        return jsonify({"unreadCount": 0, "items": [], "total": 0, "limit": limit, "offset": offset}), 200


@comm_bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@jwt_required()
def mark_notification_read(notif_id):
    user_id = int(get_jwt_identity())
    ok      = notification_service.mark_notification_read(notif_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/notifications/read-all", methods=["POST"])
@jwt_required()
def mark_all_notifications_read():
    user_id = int(get_jwt_identity())
    count   = notification_service.mark_all_read(user_id)
    return jsonify({"marked": count}), 200


# ══════════════════════════════════════════════════════════════════════════════
# CALLS (WebRTC signaling via polling)
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/calls", methods=["POST"])
@jwt_required()
def start_call():
    user_id = int(get_jwt_identity())
    data    = request.get_json(silent=True) or {}
    try:
        pids = [int(x) for x in data.get("participantIds", [])]
        call = voice_call_service.start_call(
            initiator_id    = user_id,
            participant_ids = pids,
            call_type       = data.get("callType", "voice"),
        )
        return jsonify({
            "callId":   call.id,
            "roomCode": call.room_code,
        }), 201
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@comm_bp.route("/turn-credentials", methods=["GET"])
@jwt_required()
def turn_credentials():
    user_id = int(get_jwt_identity())
    return jsonify(voice_call_service.turn_credentials(user_id)), 200


@comm_bp.route("/calls/<int:call_id>/answer", methods=["POST"])
@jwt_required()
def answer_call(call_id):
    user_id = int(get_jwt_identity())
    ok      = voice_call_service.answer_call(call_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/calls/<int:call_id>/end", methods=["POST"])
@jwt_required()
def end_call(call_id):
    user_id = int(get_jwt_identity())
    ok      = voice_call_service.end_call(call_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/calls/<int:call_id>/signal", methods=["POST"])
@jwt_required()
def send_signal(call_id):
    user_id = int(get_jwt_identity())
    data    = request.get_json(silent=True) or {}
    try:
        signal = voice_call_service.send_signal(
            call_id     = call_id,
            sender_id   = user_id,
            receiver_id = int(data["receiverId"]),
            signal_type = data["signalType"],
            payload     = data.get("payload", {}),
        )
        return jsonify({"signalId": signal.id}), 201
    except Exception as e:
        from app.extensions import db
        db.session.rollback()
        err = f"{type(e).__name__}: {e}"
        return jsonify({"error": err, "message": err}), 500


@comm_bp.route("/calls/<int:call_id>/signals", methods=["GET"])
@jwt_required()
def poll_signals(call_id):
    user_id = int(get_jwt_identity())
    return jsonify(voice_call_service.get_pending_signals(call_id, user_id)), 200


@comm_bp.route("/calls/incoming", methods=["GET"])
@jwt_required()
def incoming_calls():
    user_id = int(get_jwt_identity())
    try:
        return jsonify(voice_call_service.get_incoming_calls(user_id)), 200
    except Exception:
        return jsonify([]), 200


@comm_bp.route("/calls/<int:call_id>", methods=["GET"])
@jwt_required()
def call_detail(call_id):
    user_id = int(get_jwt_identity())
    detail  = voice_call_service.get_call_detail(call_id, user_id)
    if not detail:
        return jsonify({"error": "Not found"}), 404
    return jsonify(detail), 200


@comm_bp.route("/calls/history", methods=["GET"])
@jwt_required()
def call_history():
    user_id = int(get_jwt_identity())
    return jsonify(voice_call_service.get_call_history(user_id)), 200


# ══════════════════════════════════════════════════════════════════════════════
# MEETINGS
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/meetings", methods=["POST"])
@jwt_required()
def create_meeting():
    from datetime import datetime
    user_id = int(get_jwt_identity())
    data    = request.json
    sched   = data.get("scheduledAt")
    meeting = meeting_service.create_meeting(
        organizer_id  = user_id,
        title         = data["title"],
        meeting_type  = data.get("meetingType", "video"),
        scheduled_at  = datetime.fromisoformat(sched) if sched else None,
        agenda        = data.get("agenda"),
        invitee_ids   = [int(x) for x in data.get("inviteeIds", [])],
    )
    return jsonify({
        "meetingId":   meeting.id,
        "meetingCode": meeting.meeting_code,
    }), 201


@comm_bp.route("/meetings/mine", methods=["GET"])
@jwt_required()
def my_meetings():
    user_id     = int(get_jwt_identity())
    upcoming    = request.args.get("upcoming", "true").lower() == "true"
    return jsonify(meeting_service.get_user_meetings(user_id, upcoming)), 200


@comm_bp.route("/meetings/history", methods=["GET"])
@jwt_required()
def meeting_history():
    user_id = int(get_jwt_identity())
    return jsonify(meeting_service.get_meeting_history(user_id)), 200


@comm_bp.route("/meetings/<int:meeting_id>", methods=["GET"])
@jwt_required()
def meeting_detail(meeting_id):
    detail = meeting_service.get_meeting_detail(meeting_id)
    if not detail:
        return jsonify({"error": "Not found"}), 404
    return jsonify(detail), 200


@comm_bp.route("/meetings/<int:meeting_id>/join", methods=["POST"])
@jwt_required()
def join_meeting(meeting_id):
    user_id = int(get_jwt_identity())
    result  = meeting_service.join_meeting(meeting_id, user_id)
    if not result:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result), 200


@comm_bp.route("/meetings/<int:meeting_id>/leave", methods=["POST"])
@jwt_required()
def leave_meeting(meeting_id):
    user_id = int(get_jwt_identity())
    ok      = meeting_service.leave_meeting(meeting_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


@comm_bp.route("/meetings/<int:meeting_id>/end", methods=["POST"])
@jwt_required()
def end_meeting(meeting_id):
    user_id = int(get_jwt_identity())
    ok      = meeting_service.end_meeting(meeting_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


@comm_bp.route("/meetings/<int:meeting_id>/rsvp", methods=["POST"])
@jwt_required()
def rsvp_meeting(meeting_id):
    user_id = int(get_jwt_identity())
    rsvp    = request.json.get("rsvp", "accepted")
    ok      = meeting_service.respond_to_invite(meeting_id, user_id, rsvp)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Not found"}), 404)


# ══════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/announcements", methods=["POST"])
@jwt_required()
def create_announcement():
    from datetime import datetime
    user_id = int(get_jwt_identity())
    data    = request.json
    expires = data.get("expiresAt")
    ann = announcement_service.create_announcement(
        author_id    = user_id,
        title        = data["title"],
        body         = data["body"],
        audience_ids = [int(x) for x in data.get("audienceIds", [])],
        priority     = data.get("priority", "normal"),
        expires_at   = datetime.fromisoformat(expires) if expires else None,
    )
    return jsonify({"announcementId": ann.id}), 201


@comm_bp.route("/announcements", methods=["GET"])
@jwt_required()
def list_announcements():
    user_id = int(get_jwt_identity())
    return jsonify(announcement_service.get_active_announcements(user_id)), 200


@comm_bp.route("/announcements/<int:ann_id>/read", methods=["POST"])
@jwt_required()
def mark_announcement_read(ann_id):
    user_id = int(get_jwt_identity())
    announcement_service.mark_announcement_read(ann_id, user_id)
    return jsonify({"ok": True}), 200


@comm_bp.route("/announcements/<int:ann_id>/deactivate", methods=["POST"])
@jwt_required()
def deactivate_announcement(ann_id):
    user_id = int(get_jwt_identity())
    ok      = announcement_service.deactivate_announcement(ann_id, user_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "Forbidden"}), 403)


# ══════════════════════════════════════════════════════════════════════════════
# PRESENCE / DIRECTORY
# ══════════════════════════════════════════════════════════════════════════════

@comm_bp.route("/directory", methods=["GET"])
@jwt_required()
def directory():
    user_id = int(get_jwt_identity())
    search  = request.args.get("search")
    return jsonify(presence_integration_service.get_user_directory(user_id, search)), 200


@comm_bp.route("/presence/<int:target_user_id>", methods=["GET"])
@jwt_required()
def user_presence(target_user_id):
    return jsonify(presence_integration_service.get_rich_status(target_user_id)), 200


@comm_bp.route("/heartbeat", methods=["POST"])
@jwt_required()
def heartbeat():
    user_id = int(get_jwt_identity())
    presence_integration_service.record_heartbeat(user_id)
    return jsonify({"ok": True}), 200
