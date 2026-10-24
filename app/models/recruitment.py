from app.extensions import db


class JobOpening(db.Model):
    __tablename__ = "job_openings"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    department = db.Column(db.String(100))
    location = db.Column(db.String(100))
    openings_count = db.Column(db.Integer, default=1)
    experience_required = db.Column(db.String(50))
    job_type = db.Column(db.String(30))        # Full-time, Contract, Intern
    status = db.Column(db.String(20), default="Open")  # Open, Closed, On Hold
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    candidates = db.relationship("Candidate", backref="job_opening", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "department": self.department,
            "location": self.location,
            "openings_count": self.openings_count,
            "experience_required": self.experience_required,
            "job_type": self.job_type,
            "status": self.status,
            "description": self.description,
            "applied_count": len(self.candidates),
            "created_at": str(self.created_at) if self.created_at else None,
        }


class Candidate(db.Model):
    __tablename__ = "candidates"

    id = db.Column(db.Integer, primary_key=True)
    job_opening_id = db.Column(db.Integer, db.ForeignKey("job_openings.id"))
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120))
    mobile = db.Column(db.String(20))
    resume_url = db.Column(db.String(500))
    stage = db.Column(db.String(30), default="Applied")
    # Applied | Screening | Interview | Offer | Joined | Rejected
    applied_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    current_ctc = db.Column(db.String(50))
    expected_ctc = db.Column(db.String(50))
    notice_period = db.Column(db.String(30))
    source = db.Column(db.String(50))   # LinkedIn, Referral, Job Portal, Walk-in
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "job_opening_id": self.job_opening_id,
            "job_title": self.job_opening.title if self.job_opening else None,
            "name": self.name,
            "email": self.email,
            "mobile": self.mobile,
            "resume_url": self.resume_url,
            "stage": self.stage,
            "applied_date": str(self.applied_date) if self.applied_date else None,
            "notes": self.notes,
            "current_ctc": self.current_ctc,
            "expected_ctc": self.expected_ctc,
            "notice_period": self.notice_period,
            "source": self.source,
            "created_at": str(self.created_at) if self.created_at else None,
        }
