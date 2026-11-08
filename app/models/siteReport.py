"""Daily Progress Report (DPR) built from site photos.

SitePhoto            one photo from the site — the mobile camera (time and GPS
                     stamped) or a web upload — plus what the AI saw in it.
DailyProgressReport  one report per project per day, written by AI from that
                     day's photos and site records, then reviewed and approved
                     through the normal workflow (module code "daily_progress_report").
"""

from datetime import datetime

from app.extensions import db


class SitePhoto(db.Model):
    __tablename__ = "site_photos"
    __table_args__ = (
        db.Index("ix_site_photos_project_date", "project_code", "report_date"),
        db.UniqueConstraint("project_code", "sha256", name="uq_site_photos_project_sha256"),
    )

    id = db.Column(db.Integer, primary_key=True)
    photo_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)

    project_code = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)

    # Site day the photo belongs to (India time).
    report_date = db.Column(db.Date, nullable=False)

    # ── When & where ───────────────────────────────────────────────
    taken_at = db.Column(db.DateTime, nullable=False)          # India time
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    source = db.Column(db.String(20), nullable=False)           # camera | upload
    time_source = db.Column(db.String(20))                      # device | exif | upload
    time_verified = db.Column(db.Boolean, default=False)

    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    accuracy_m = db.Column(db.Float)
    distance_m = db.Column(db.Float)                            # from the project site, when known
    on_site = db.Column(db.Boolean)                             # None = site location not set
    is_mock_location = db.Column(db.Boolean, default=False)

    sub_location = db.Column(db.String(200))
    caption = db.Column(db.String(500))

    # ── File ───────────────────────────────────────────────────────
    file_url = db.Column(db.Text, nullable=False)
    thumb_url = db.Column(db.Text)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    sha256 = db.Column(db.String(64), nullable=False)

    # ── AI reading ─────────────────────────────────────────────────
    ai_status = db.Column(db.String(20), default="pending")     # pending | working | done | failed | skipped
    ai_result = db.Column(db.JSON)
    ai_error = db.Column(db.Text)
    ai_at = db.Column(db.DateTime)
    ai_model = db.Column(db.String(60))
    safety_alert_sent = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(20), default="Active")         # Active | Deleted
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    uploader = db.relationship("User", foreign_keys=[uploaded_by])


class DailyProgressReport(db.Model):
    __tablename__ = "daily_progress_reports"
    __table_args__ = (
        db.UniqueConstraint("project_code", "report_date", name="uq_dpr_project_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    dpr_no = db.Column(db.String(50), unique=True, nullable=False)
    dpr_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)

    project_code = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)
    report_date = db.Column(db.Date, nullable=False)

    # ── Content (AI draft, editable) ───────────────────────────────
    summary = db.Column(db.Text)
    content = db.Column(db.JSON)          # sections: work done, manpower, machinery, materials, issues, safety …
    weather = db.Column(db.String(200))
    manpower_total = db.Column(db.Integer)
    photo_count = db.Column(db.Integer, default=0)
    highlight_photo_ids = db.Column(db.JSON)

    generated_at = db.Column(db.DateTime)
    generated_by = db.Column(db.String(20))   # auto | manual
    ai_model = db.Column(db.String(60))
    edited = db.Column(db.Boolean, default=False)
    remarks = db.Column(db.Text)              # engineer's own notes

    # ── Workflow ───────────────────────────────────────────────────
    workflow_status = db.Column(db.String(30), default="Draft")
    status = db.Column(db.String(30), default="Active")
    current_level = db.Column(db.Integer, default=0)
    locked = db.Column(db.Boolean, default=False)

    # ── Audit ──────────────────────────────────────────────────────
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at = db.Column(db.DateTime)
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    project = db.relationship("Project", backref="daily_progress_reports")
    creator = db.relationship("User", foreign_keys=[created_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
