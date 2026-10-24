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
    salary_band = db.Column(db.String(100))
    deadline = db.Column(db.Date)
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
            "in_progress_count": sum(1 for c in self.candidates if c.stage not in ("Joined", "Rejected")),
            "salary_band": self.salary_band,
            "deadline": str(self.deadline) if self.deadline else None,
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
    offer_letter_generated = db.Column(db.Boolean, default=False)
    appointment_letter_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "job_opening_id": self.job_opening_id,
            "job_title": self.job_opening.title if self.job_opening else None,
            "department": self.job_opening.department if self.job_opening else None,
            "location": self.job_opening.location if self.job_opening else None,
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
            "offer_letter_generated": self.offer_letter_generated or False,
            "appointment_letter_generated": self.appointment_letter_generated or False,
            "created_at": str(self.created_at) if self.created_at else None,
        }


class Interview(db.Model):
    __tablename__ = "interviews"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), nullable=False)
    scheduled_date = db.Column(db.Date)
    scheduled_time = db.Column(db.String(20))
    round_name = db.Column(db.String(100))
    mode = db.Column(db.String(30), default="Video Call")  # Video Call, In-Person, Phone
    interviewer = db.Column(db.String(200))
    status = db.Column(db.String(20), default="Scheduled")  # Scheduled, Completed, Cancelled
    score = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    decision = db.Column(db.String(20))  # Advance, Reject, Hold
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    candidate = db.relationship("Candidate", backref="interviews", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate.name if self.candidate else None,
            "job_title": self.candidate.job_opening.title if self.candidate and self.candidate.job_opening else None,
            "scheduled_date": str(self.scheduled_date) if self.scheduled_date else None,
            "scheduled_time": self.scheduled_time,
            "round_name": self.round_name,
            "mode": self.mode,
            "interviewer": self.interviewer,
            "status": self.status,
            "score": self.score,
            "feedback": self.feedback,
            "decision": self.decision,
            "created_at": str(self.created_at) if self.created_at else None,
        }
