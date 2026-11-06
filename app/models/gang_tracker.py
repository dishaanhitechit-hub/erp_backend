from app.extensions import db
from datetime import datetime


class GangMember(db.Model):
    __tablename__ = "gang_members"

    id = db.Column(db.Integer, primary_key=True)

    name     = db.Column(db.String(200), nullable=False)
    skill    = db.Column(db.String(100), nullable=True)
    mobile   = db.Column(db.String(20), nullable=False)
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
