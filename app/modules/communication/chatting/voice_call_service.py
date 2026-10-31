import json
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.communication_models import (
    CommCall,
    CommCallParticipant,
    CommCallSignal,
)
from app.modules.communication.chatting.notification_service import push_notification


RING_TIMEOUT = timedelta(seconds=45)


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def start_call(
    initiator_id:   int,
    participant_ids: list,
    call_type:      str = "voice",
    room_code:      str = None,
) -> CommCall:
    from app.models.user import User
    import secrets

    if not room_code:
        room_code = secrets.token_urlsafe(12)

    call = CommCall(
        initiator_id = initiator_id,
        call_type    = call_type,
        room_code    = room_code,
        status       = "ringing",
        started_at   = _now(),
    )
    db.session.add(call)
    db.session.flush()

    db.session.add(CommCallParticipant(
        call_id   = call.id,
        user_id   = initiator_id,
        status    = "in_call",
        joined_at = _now(),
    ))

    for uid in participant_ids:
        if uid == initiator_id:
            continue
        db.session.add(CommCallParticipant(
            call_id = call.id,
            user_id = uid,
            status  = "ringing",
        ))

    db.session.commit()

    initiator = db.session.get(User, initiator_id)
    name      = initiator.username if initiator else "Someone"
    for uid in participant_ids:
        if uid != initiator_id:
            push_notification(
                user_id           = uid,
                notification_type = "incoming_call",
                title             = f"Incoming {call_type} call from {name}",
                data              = {
                    "callId":   call.id,
                    "callType": call_type,
                    "roomCode": room_code,
                },
            )

    return call


def answer_call(call_id: int, user_id: int) -> bool:
    call = db.session.get(CommCall, call_id)
    if not call:
        return False

    part = CommCallParticipant.query.filter_by(
        call_id=call_id, user_id=user_id
    ).first()
    if not part:
        return False

    part.status   = "in_call"
    part.joined_at = _now()
    if call.status == "ringing":
        call.status = "active"
    db.session.commit()
    return True


def send_signal(
    call_id:     int,
    sender_id:   int,
    receiver_id: int,
    signal_type: str,
    payload:     dict,
) -> CommCallSignal:
    signal = CommCallSignal(
        call_id     = call_id,
        sender_id   = sender_id,
        receiver_id = receiver_id,
        signal_type = signal_type,
        payload     = json.dumps(payload),
        created_at  = _now(),
    )
    db.session.add(signal)
    db.session.commit()
    return signal


def get_pending_signals(call_id: int, user_id: int) -> list:
    signals = (
        CommCallSignal.query
        .filter_by(call_id=call_id, receiver_id=user_id, is_consumed=False)
        .order_by(CommCallSignal.created_at.asc())
        .all()
    )
    result = []
    for s in signals:
        s.is_consumed = True
        result.append({
            "signalId":   s.id,
            "senderId":   s.sender_id,
            "signalType": s.signal_type,
            "payload":    json.loads(s.payload) if s.payload else {},
            "createdAt":  s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
    db.session.commit()
    return result


def end_call(call_id: int, user_id: int) -> bool:
    call = db.session.get(CommCall, call_id)
    if not call:
        return False

    now = _now()
    call.status   = "ended"
    call.ended_at = now

    if call.started_at:
        delta = now - _aware(call.started_at)
        call.duration_seconds = int(delta.total_seconds())

    other_ids = []
    for part in call.participants:
        if part.status in ("in_call", "ringing"):
            part.status  = "ended"
            part.left_at = now
        if part.user_id != user_id:
            other_ids.append(part.user_id)

    db.session.commit()

    # Notify other participants immediately via signal so they don't wait for poll
    for uid in other_ids:
        try:
            send_signal(call_id, user_id, uid, "ended", {})
        except Exception:
            db.session.rollback()

    return True


def get_incoming_calls(user_id: int) -> list:
    ringing = (
        CommCallParticipant.query
        .filter_by(user_id=user_id, status="ringing")
        .order_by(CommCallParticipant.id.desc())
        .all()
    )
    cutoff  = _now() - RING_TIMEOUT
    result  = []
    expired = False
    for part in ringing:
        call = part.call
        if not call or call.status != "ringing":
            part.status = "missed"
            expired = True
            continue
        started = _aware(call.started_at or call.created_at)
        if started and started < cutoff:
            # Caller vanished without hanging up — never offer this call again
            call.status = "missed"
            part.status = "missed"
            expired = True
            continue
        result.append(_call_dict(call, user_id))
    if expired:
        db.session.commit()
    return result


def get_call_detail(call_id: int, user_id: int) -> dict | None:
    call = db.session.get(CommCall, call_id)
    if not call:
        return None
    return _call_dict(call, user_id)


def update_participant_state(call_id: int, user_id: int, state: str) -> bool:
    part = CommCallParticipant.query.filter_by(
        call_id=call_id, user_id=user_id
    ).first()
    if not part:
        return False
    part.status = state
    db.session.commit()
    return True


def get_call_history(user_id: int, limit: int = 20) -> list:
    parts = (
        CommCallParticipant.query
        .filter_by(user_id=user_id)
        .order_by(CommCallParticipant.id.desc())
        .limit(limit)
        .all()
    )
    return [_call_dict(p.call, user_id) for p in parts if p.call]


def _call_dict(call: CommCall, user_id: int) -> dict:
    from app.models.user import User

    participants = []
    for p in call.participants:
        u = db.session.get(User, p.user_id)
        participants.append({
            "userId":   p.user_id,
            "userName": u.username if u else None,
            "state":    p.status,
            "joinedAt": p.joined_at.strftime("%Y-%m-%d %H:%M:%S") if p.joined_at else None,
        })

    initiator = db.session.get(User, call.initiator_id)
    return {
        "callId":          call.id,
        "callType":        call.call_type,
        "status":          call.status,
        "roomCode":        call.room_code,
        "initiatorId":     call.initiator_id,
        "initiatorName":   initiator.username if initiator else None,
        "durationSeconds": call.duration_seconds,
        "participants":    participants,
        "startedAt":       call.started_at.strftime("%Y-%m-%d %H:%M:%S") if call.started_at else None,
        "endedAt":         call.ended_at.strftime("%Y-%m-%d %H:%M:%S") if call.ended_at else None,
    }
