from app.utils.date_utils import created_ts
from app.extensions import db
from datetime import datetime


class GangMember(db.Model):
    __tablename__ = "gang_members"

    id = db.Column(db.Integer, primary_key=True)

    name     = db.Column(db.String(200), nullable=False)
    skill    = db.Column(db.String(100), nullable=True)
    mobile   = db.Column(db.String(20), nullable=True)   # optional: names auto-registered from conversations may have no number yet
    whatsapp = db.Column(db.String(20), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    status   = db.Column(db.String(30), default="Available")   # Available / Deployed / Follow-up / Pending / Unavailable
    site     = db.Column(db.String(200), nullable=True)        # current site / project
    followup_date = db.Column(db.Date, nullable=True)
    notes    = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user = db.relationship("User", backref="created_gang_members", lazy=True)

    logs = db.relationship("GangFollowupLog", backref="member", lazy=True,
                           cascade="all, delete-orphan", order_by="GangFollowupLog.log_date")

    def to_dict(self):
        last_log = self.logs[-1] if self.logs else None
        return {
            "id":           self.id,
            "name":         self.name,
            "skill":        self.skill,
            "mobile":       self.mobile,
            "whatsapp":     self.whatsapp,
            "location":     self.location,
            "status":       self.status,
            "site":         self.site,
            "followup":     self.followup_date.isoformat() if self.followup_date else None,
            "notes":        self.notes,
            "log": [l.to_dict() for l in self.logs],
            "last_log":     last_log.to_dict() if last_log else None,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
            "createdTs": created_ts(self.created_at),
        }

    def __repr__(self):
        return f"<GangMember {self.id} - {self.name}>"


class GangFollowupLog(db.Model):
    __tablename__ = "gang_followup_logs"

    id        = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="CASCADE"), nullable=False)
    log_date  = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    note      = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":       self.id,
            "date":     self.log_date.isoformat() if self.log_date else None,
            "note":     self.note,
        }


# ── Conversations ────────────────────────────────────────────────────────────
# One conversation = one topic/agenda (optionally about a project) that may pass
# through several people: talk to A → A refers you to B → back to A in 3 days.
# Each step is an append-only GangThreadEntry, so the history reads like a
# commit graph (one lane per person, a branch line where someone is referred).

THREAD_STATUSES = ("Ongoing", "Scheduled", "Waiting", "Done", "Dropped")
CLOSED_STATUSES = ("Done", "Dropped")


def _mini(m):
    return {"id": m.id, "name": m.name, "skill": m.skill, "mobile": m.mobile} if m else None


class GangThread(db.Model):
    __tablename__ = "gang_threads"

    id      = db.Column(db.Integer, primary_key=True)
    topic   = db.Column(db.String(300), nullable=False)          # agenda — what this is about
    project = db.Column(db.String(200), nullable=True)           # free text; suggestions come from projects + past use
    status  = db.Column(db.String(20), nullable=False, default="Ongoing")

    started_with_id = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="SET NULL"), nullable=True)
    next_member_id  = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="SET NULL"), nullable=True)
    next_followup_date = db.Column(db.Date, nullable=True)
    next_action     = db.Column(db.String(300), nullable=True)

    closed_at  = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    started_with = db.relationship("GangMember", foreign_keys=[started_with_id], lazy="joined")
    next_member  = db.relationship("GangMember", foreign_keys=[next_member_id], lazy="joined")
    created_by_user = db.relationship("User", foreign_keys=[created_by], lazy=True)
    entries = db.relationship("GangThreadEntry", backref="thread", lazy="selectin", cascade="all, delete-orphan",
                              order_by="(GangThreadEntry.entry_date, GangThreadEntry.id)")

    def people(self):
        """Everyone involved, in order of first appearance (lane order for the graph)."""
        seen, out = set(), []
        for m in [self.started_with] + [x for e in self.entries for x in (e.member, e.referred_to, e.next_member)]:
            if m and m.id not in seen:
                seen.add(m.id)
                out.append(m)
        return out

    def to_dict(self, with_entries=False):
        last = self.entries[-1] if self.entries else None
        d = {
            "id": self.id,
            "topic": self.topic,
            "project": self.project,
            "status": self.status,
            "startedWith": _mini(self.started_with),
            "nextMember": _mini(self.next_member),
            "nextFollowup": self.next_followup_date.isoformat() if self.next_followup_date else None,
            "nextAction": self.next_action,
            "people": [_mini(m) for m in self.people()],
            "entryCount": len(self.entries),
            "lastEntry": last.to_dict() if last else None,
            "closedAt": self.closed_at.isoformat() if self.closed_at else None,
            "createdBy": self.created_by_user.username if self.created_by_user else None,
            "updatedTs": created_ts(self.updated_at),
            "createdTs": created_ts(self.created_at),
        }
        if with_entries:
            d["entries"] = [e.to_dict() for e in self.entries]
        return d


class GangThreadEntry(db.Model):
    __tablename__ = "gang_thread_entries"

    id         = db.Column(db.Integer, primary_key=True)
    thread_id  = db.Column(db.Integer, db.ForeignKey("gang_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False)
    member_id  = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="SET NULL"), nullable=True)   # who we talked to
    note       = db.Column(db.Text, nullable=True)                                                              # what was discussed
    referred_to_id = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="SET NULL"), nullable=True)
    next_member_id = db.Column(db.Integer, db.ForeignKey("gang_members.id", ondelete="SET NULL"), nullable=True)
    next_followup_date = db.Column(db.Date, nullable=True)
    next_action  = db.Column(db.String(300), nullable=True)
    status_after = db.Column(db.String(20), nullable=True)      # thread status this step left it in

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    member      = db.relationship("GangMember", foreign_keys=[member_id], lazy="joined")
    referred_to = db.relationship("GangMember", foreign_keys=[referred_to_id], lazy="joined")
    next_member = db.relationship("GangMember", foreign_keys=[next_member_id], lazy="joined")
    created_by_user = db.relationship("User", foreign_keys=[created_by], lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.entry_date.isoformat() if self.entry_date else None,
            "member": _mini(self.member),
            "note": self.note,
            "referredTo": _mini(self.referred_to),
            "nextMember": _mini(self.next_member),
            "nextFollowup": self.next_followup_date.isoformat() if self.next_followup_date else None,
            "nextAction": self.next_action,
            "statusAfter": self.status_after,
            "by": self.created_by_user.username if self.created_by_user else None,
            "createdTs": created_ts(self.created_at),
        }
