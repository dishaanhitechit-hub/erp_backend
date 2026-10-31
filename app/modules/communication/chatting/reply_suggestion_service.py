import re

from app.extensions import db
from app.models.communication_models import CommMessage

MAX_SUGGESTIONS = 3

# Checked top to bottom; the first rules that match fill the suggestion list.
# To improve suggestions (or swap in an AI model later), change only this file —
# the API shape {"suggestions": [...]} stays the same for every caller.
_RULES = [
    (r"\b(thanks|thank you|thx|thnx|tnx|dhanyavad)\b",
        ["You're welcome!", "No problem", "Anytime"]),
    (r"\b(sorry|apologies|my bad)\b",
        ["No worries", "It's okay", "Noted"]),
    (r"\b(urgent|asap|immediately|right now|jaldi)\b",
        ["On it", "Will do it right away", "Give me 10 minutes"]),
    (r"\b(approve|approval|sign|signature|authorise|authorize)\b",
        ["Approved", "Will review shortly", "Please share the details"]),
    (r"\b(review|check|verify|look into|dekho|dekh lo)\b",
        ["Will check and revert", "Checked, looks good", "Give me some time"]),
    (r"\b(meeting|meet|call me|join|conference)\b",
        ["Joining now", "What time?", "Can we do it later?"]),
    (r"\b(when|kab|what time|eta|by when)\b",
        ["Today", "Tomorrow", "Will update you"]),
    (r"\b(where|kaha|kahan)\b",
        ["At site", "In office", "On the way"]),
    (r"\b(send|share|bhejo|forward)\b",
        ["Sending now", "Sure, will share", "Shared"]),
    (r"\b(done|completed|finished|ho gaya|hogaya)\b",
        ["Great, thanks!", "Noted", "Perfect"]),
    (r"\b(hi|hello|hey|hii|good morning|good afternoon|good evening|namaste)\b",
        ["Hi!", "Hello, how can I help?", "Good day!"]),
    (r"\b(ok|okay|thik hai|theek hai|fine|noted)\b",
        ["Great", "Thanks", "👍"]),
]

_QUESTION   = ["Yes, sure", "No, sorry", "Let me check"]
_BY_TYPE    = {
    "image": ["Looks good", "Received, thanks", "Nice"],
    "video": ["Received, thanks", "Will watch it", "Looks good"],
    "audio": ["Received, will listen", "Okay, noted", "Thanks"],
    "file":  ["Received, thanks", "Will check and revert", "Got it"],
}
_FALLBACK   = ["OK", "Noted", "Thanks!"]


def suggest_replies(text: str = None, message_type: str = "text") -> list:
    matched = []
    if message_type in _BY_TYPE:
        matched.append(_BY_TYPE[message_type])

    lowered = (text or "").lower().strip()
    if lowered:
        matched += [replies for pattern, replies in _RULES if re.search(pattern, lowered)]
        if lowered.endswith("?") or re.match(r"^(can|could|will|would|please|pls|plz|kindly|is|are|do|did)\b", lowered):
            matched.append(_QUESTION)
    if not matched:
        matched.append(_FALLBACK)

    # Round-robin across matched rules so a message hitting several topics gets a mix
    suggestions = []
    for i in range(max(len(m) for m in matched)):
        for replies in matched:
            if i < len(replies) and replies[i] not in suggestions:
                suggestions.append(replies[i])
            if len(suggestions) == MAX_SUGGESTIONS:
                return suggestions
    return suggestions


def suggestions_for_message(message_id: int, user_id: int) -> list:
    from app.modules.communication.chatting.media_service import is_member

    msg = db.session.get(CommMessage, message_id)
    if not msg or msg.is_deleted or not is_member(msg.conversation_id, user_id):
        return []
    if msg.sender_id == user_id:
        return []
    return suggest_replies(msg.content, msg.message_type)
