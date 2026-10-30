import secrets
from datetime import datetime, timezone
from app.extensions import db
from app.models.communication_models import (
    CommMeeting,
    CommMeetingParticipant,
    CommCall,
    CommCallParticipant,
)
from app.modules.communication.chatting.notification_service import push_to_many


def _now():
    return datetime.now(timezone.utc)


def create_meeting(
    organizer_id:   int,
    title:          str,
    meeting_type:   str       = "video",
    scheduled_at:   datetime  = None,
    agenda:         str       = None,
    invitee_ids:    list      = None,
) -> CommMeeting:
    from app.models.user import User

    meeting_code = secrets.token_urlsafe(8).upper()
    meeting = CommMeeting(
        organizer_id  = organizer_id,
        title         = title,
        meeting_type  = meeting_type,
        scheduled_at  = scheduled_at,
        agenda        = agenda,
        meeting_code  = meeting_code,
        status        = "scheduled",
        created_at    = _now(),
    )
    db.session.add(meeting)
    db.session.flush()

    db.session.add(CommMeetingParticipant(
        meeting_id = meeting.id,
        user_id    = organizer_id,
        role       = "organizer",
        rsvp       = "accepted",
    ))

    invitee_ids = invitee_ids or []
    for uid in invitee_ids:
        if uid != organizer_id:
            db.session.add(CommMeetingParticipant(
                meeting_id = meeting.id,
                user_id    = uid,
                role       = "participant",
                rsvp       = "pending",
            ))

    db.session.commit()

    if invitee_ids:
        organizer    = db.session.get(User, organizer_id)
        org_name     = organizer.username if organizer else "Someone"
        push_to_many(
            user_ids          = [uid for uid in invitee_ids if uid != organizer_id],
            notification_type = "meeting_invite",
            title             = f"Meeting invite: {title}",
            body              = f"Invited by {org_name}",
            data              = {
                "meetingId":   meeting.id,
                "meetingCode": meeting_code,
                "meetingType": meeting_type,
            },
        )

    return meeting


def join_meeting(meeting_id: int, user_id: int) -> dict | None:
    meeting = db.session.get(CommMeeting, meeting_id)
    if not meeting:
        return None

    part = CommMeetingParticipant.query.filter_by(
        meeting_id=meeting_id, user_id=user_id
    ).first()
    if not part:
        part = CommMeetingParticipant(
            meeting_id = meeting_id,
            user_id    = user_id,
            role       = "participant",
            rsvp       = "accepted",
        )
        db.session.add(part)

    part.rsvp      = "accepted"
    part.joined_at = _now()

    if meeting.status == "scheduled":
        meeting.status     = "active"
        meeting.started_at = _now()

    call = _get_or_create_meeting_call(meeting, user_id)

    db.session.add(CommCallParticipant(
        call_id   = call.id,
        user_id   = user_id,
        state     = "in_call",
        joined_at = _now(),
    ))
    db.session.commit()

    return {
        "meetingId":   meeting.id,
        "meetingCode": meeting.meeting_code,
        "callId":      call.id,
        "roomCode":    call.room_code,
        "status":      meeting.status,
    }


def leave_meeting(meeting_id: int, user_id: int) -> bool:
    meeting = db.session.get(CommMeeting, meeting_id)
    if not meeting:
        return False

    part = CommMeetingParticipant.query.filter_by(
        meeting_id=meeting_id, user_id=user_id
    ).first()
    if part:
        part.left_at = _now()

    call = CommCall.query.filter_by(
        room_code=f"mtg_{meeting.meeting_code}",
        status="active",
    ).first()
    if call:
        call_part = CommCallParticipant.query.filter_by(
            call_id=call.id, user_id=user_id, state="in_call"
        ).first()
        if call_part:
            call_part.state   = "ended"
            call_part.left_at = _now()

    db.session.commit()
    return True


def end_meeting(meeting_id: int, organizer_id: int) -> bool:
    meeting = db.session.get(CommMeeting, meeting_id)
    if not meeting or meeting.organizer_id != organizer_id:
        return False

    now = _now()
    meeting.status   = "ended"
    meeting.ended_at = now

    call = CommCall.query.filter_by(
        room_code=f"mtg_{meeting.meeting_code}",
    ).first()
    if call and call.status == "active":
        call.status   = "ended"
        call.ended_at = now
        if call.started_at:
            call.duration_seconds = int((now - call.started_at).total_seconds())
        for p in call.participants:
            if p.state == "in_call":
                p.state   = "ended"
                p.left_at = now

    db.session.commit()
    return True


def respond_to_invite(meeting_id: int, user_id: int, rsvp: str) -> bool:
    """rsvp: accepted | declined | tentative"""
    part = CommMeetingParticipant.query.filter_by(
        meeting_id=meeting_id, user_id=user_id
    ).first()
    if not part:
        return False
    part.rsvp = rsvp
    db.session.commit()
    return True


def get_meeting_detail(meeting_id: int) -> dict | None:
    meeting = db.session.get(CommMeeting, meeting_id)
    if not meeting:
        return None
    return _meeting_dict(meeting)


def get_user_meetings(user_id: int, upcoming_only: bool = True) -> list:
    query = (
        CommMeetingParticipant.query
        .filter_by(user_id=user_id)
    )
    meetings = [p.meeting for p in query.all() if p.meeting]
    if upcoming_only:
        now      = _now()
        meetings = [m for m in meetings if m.status in ("scheduled", "active")]
    meetings.sort(
        key=lambda m: m.scheduled_at or m.created_at,
    )
    return [_meeting_dict(m) for m in meetings]


def get_meeting_history(user_id: int, limit: int = 20) -> list:
    parts = (
        CommMeetingParticipant.query
        .filter_by(user_id=user_id)
        .all()
    )
    meetings = [
        p.meeting for p in parts
        if p.meeting and p.meeting.status == "ended"
    ]
    meetings.sort(key=lambda m: m.ended_at or m.created_at, reverse=True)
    return [_meeting_dict(m) for m in meetings[:limit]]


def _get_or_create_meeting_call(meeting: CommMeeting, creator_id: int) -> CommCall:
    room_code = f"mtg_{meeting.meeting_code}"
    call = CommCall.query.filter_by(room_code=room_code).first()
    if not call:
        call = CommCall(
            initiator_id = creator_id,
            call_type    = meeting.meeting_type or "video",
            room_code    = room_code,
            status       = "active",
            started_at   = _now(),
        )
        db.session.add(call)
        db.session.flush()
    return call


def _meeting_dict(meeting: CommMeeting) -> dict:
    from app.models.user import User

    participants = []
    for p in meeting.participants:
        u = db.session.get(User, p.user_id)
        participants.append({
            "userId":   p.user_id,
            "userName": u.username if u else None,
            "role":     p.role,
            "rsvp":     p.rsvp,
            "joinedAt": p.joined_at.strftime("%Y-%m-%d %H:%M:%S") if p.joined_at else None,
        })

    organizer = db.session.get(User, meeting.organizer_id)
    return {
        "meetingId":    meeting.id,
        "meetingCode":  meeting.meeting_code,
        "title":        meeting.title,
        "meetingType":  meeting.meeting_type,
        "status":       meeting.status,
        "agenda":       meeting.agenda,
        "organizerId":  meeting.organizer_id,
        "organizerName":organizer.username if organizer else None,
        "participants": participants,
        "scheduledAt":  meeting.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if meeting.scheduled_at else None,
        "startedAt":    meeting.started_at.strftime("%Y-%m-%d %H:%M:%S") if meeting.started_at else None,
        "endedAt":      meeting.ended_at.strftime("%Y-%m-%d %H:%M:%S") if meeting.ended_at else None,
        "createdAt":    meeting.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
