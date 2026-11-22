# app/models/issueTracker.py
"""
Issues & Feature Requests list (client writes items, developers tick them done).

  * app_setting          — small key/value settings table; holds the
                           'issue_tracker.enabled' kill switch.
  * issue_tracker_member — who may use the page. Super admin manages it:
                           can_edit = may create / edit / delete items,
                           is_developer = may tick items done.
                           A member with neither flag is view only.
  * issue_tracker_item   — one issue / feature request (sanitized HTML body)
                           plus the developer's done tick, comment, pictures.
"""

from app.extensions import db


class AppSetting(db.Model):
    __tablename__ = "app_setting"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.JSON, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())


class IssueTrackerMember(db.Model):
    __tablename__ = "issue_tracker_member"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    can_edit = db.Column(db.Boolean, nullable=False, default=False)
    is_developer = db.Column(db.Boolean, nullable=False, default=False)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    added_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", foreign_keys=[user_id])


class IssueTrackerItem(db.Model):
    __tablename__ = "issue_tracker_item"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, default="ISSUE")  # ISSUE | FEATURE
    body_html = db.Column(db.Text, nullable=False)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    is_done = db.Column(db.Boolean, nullable=False, default=False, index=True)
    done_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    done_at = db.Column(db.DateTime, nullable=True)
    done_comment = db.Column(db.Text, nullable=True)
    done_images = db.Column(db.JSON, nullable=True)  # list of URLs

    __table_args__ = (
        db.CheckConstraint("kind IN ('ISSUE', 'FEATURE')", name="ck_issue_tracker_item_kind"),
    )
