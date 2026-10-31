import mimetypes
import os
import uuid

from app.extensions import db
from app.models.communication_models import CommConversationMember, CommMessage
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.communication.chatting import message_service
from app.modules.communication.chatting.chat_service import get_or_create_direct_conversation

MAX_FILE_BYTES = 25 * 1024 * 1024

# Whitelist only — uploads are served from the ERP's own origin, so anything a
# browser would execute (html, svg, js) must never be accepted.
ALLOWED_EXTENSIONS = {
    "jpg": "image", "jpeg": "image", "png": "image", "gif": "image", "webp": "image",
    "mp4": "video", "webm": "video", "mov": "video",
    "mp3": "audio", "wav": "audio", "ogg": "audio", "m4a": "audio",
    "pdf": "file", "doc": "file", "docx": "file", "xls": "file", "xlsx": "file",
    "ppt": "file", "pptx": "file", "txt": "file", "csv": "file", "zip": "file",
}


class MediaError(ValueError):
    pass


def is_member(conversation_id: int, user_id: int) -> bool:
    return CommConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=user_id, left_at=None,
    ).first() is not None


def _file_size(file) -> int:
    pos = file.stream.tell()
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(pos)
    return size


def _validate(file) -> tuple[str, str, int]:
    if not file or not file.filename:
        raise MediaError("No file provided")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    kind = ALLOWED_EXTENSIONS.get(ext)
    if not kind:
        raise MediaError(f"File type .{ext or '?'} is not allowed")
    size = _file_size(file)
    if size > MAX_FILE_BYTES:
        raise MediaError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    return ext, kind, size


def send_media_message(
    conversation_id: int,
    sender_id:       int,
    file,
    caption:         str = None,
    reply_to_id:     int = None,
) -> CommMessage:
    if not is_member(conversation_id, sender_id):
        raise PermissionError("Not a member of this conversation")

    ext, kind, size = _validate(file)
    original_name = os.path.basename(file.filename)[:255]

    url = upload_file_to_bunny(file, "communication", f"conv_{conversation_id}", uuid.uuid4().hex)
    if not url:
        raise MediaError("Upload failed")

    return message_service.send_message(
        conversation_id = conversation_id,
        sender_id       = sender_id,
        content         = (caption or "").strip() or None,
        message_type    = kind,
        file_url        = url,
        file_name       = original_name,
        file_size       = size,
        file_mime       = mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream",
        reply_to_id     = reply_to_id,
    )


def forward_message(
    message_id:       int,
    user_id:          int,
    target_user_ids:  list = None,
    target_conv_ids:  list = None,
    caption:          str  = None,
) -> list:
    """Re-sends an existing message (text or media) to other people/conversations.
    The file itself is not copied — the new message points at the same URL."""
    src = db.session.get(CommMessage, message_id)
    if not src or src.is_deleted or not is_member(src.conversation_id, user_id):
        raise PermissionError("Message not found")

    conv_ids = []
    for uid in target_user_ids or []:
        uid = int(uid)
        if uid != user_id:
            conv_ids.append(get_or_create_direct_conversation(user_id, uid).id)
    for cid in target_conv_ids or []:
        cid = int(cid)
        if is_member(cid, user_id):
            conv_ids.append(cid)
    if not conv_ids:
        raise MediaError("No valid recipients")

    caption = (caption or "").strip()
    sent = []
    for cid in dict.fromkeys(conv_ids):
        msg = message_service.send_message(
            conversation_id = cid,
            sender_id       = user_id,
            content         = caption or src.content,
            message_type    = src.message_type,
            file_url        = src.file_url,
            file_name       = src.file_name,
            file_size       = src.file_size,
            file_mime       = src.file_mime,
        )
        sent.append({"conversationId": cid, "messageId": msg.id})
    return sent
