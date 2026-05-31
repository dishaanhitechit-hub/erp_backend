# # app/models/user_activity_model.py
# #
# # Three new tables — completely independent of all existing tables.
# # Do NOT import this from existing models/__init__.py yet;
# # see INTEGRATION NOTE at the bottom of this file.
#
# from datetime import datetime
# from app.extensions import db
#
#
# # ─────────────────────────────────────────────────────────────────────────────
# # TABLE 1 : user_presence
# #
# # One row per user.  Updated on every tracked activity.
# # Status (ACTIVE / IDLE / OFFLINE) is computed at query time
# # from last_activity_at — never stored — so it never goes stale.
# # ─────────────────────────────────────────────────────────────────────────────
#
# class UserPresence(db.Model):
#
#     __tablename__ = "user_presence"
#
#     id = db.Column(db.Integer, primary_key=True)
#
#     user_id = db.Column(
#         db.Integer,
#         db.ForeignKey("users.id", ondelete="CASCADE"),
#         nullable=False,
#         unique=True,        # one row per user
#         index=True
#     )
#
#     # Where the user currently is
#     current_module     = db.Column(db.String(60),  nullable=True)
#     current_screen     = db.Column(db.String(100), nullable=True)
#     current_record_id  = db.Column(db.Integer,     nullable=True)
#     current_record_ref = db.Column(db.String(100), nullable=True)
#
#     # Session / timing
#     session_started_at = db.Column(db.DateTime, nullable=True)
#     last_activity_at   = db.Column(db.DateTime, nullable=True, index=True)
#     ip_address         = db.Column(db.String(45), nullable=True)
#
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)
#     updated_at = db.Column(
#         db.DateTime,
#         default=datetime.utcnow,
#         onupdate=datetime.utcnow
#     )
#
#     # Relationship
#     user = db.relationship("User", backref="presence", lazy=True)
#
#     def __repr__(self):
#         return f"<UserPresence user={self.user_id}>"
#
#
# # ─────────────────────────────────────────────────────────────────────────────
# # TABLE 2 : user_activity_log
# #
# # Append-only log of every meaningful user action.
# # Never updated, never deleted in production.
# # ─────────────────────────────────────────────────────────────────────────────
#
# class UserActivityLog(db.Model):
#
#     __tablename__ = "user_activity_log"
#
#     id = db.Column(db.Integer, primary_key=True)
#
#     user_id = db.Column(
#         db.Integer,
#         db.ForeignKey("users.id", ondelete="SET NULL"),
#         nullable=True,
#         index=True
#     )
#
#     # What the user was doing
#     module     = db.Column(db.String(60),  nullable=True, index=True)
#     screen     = db.Column(db.String(100), nullable=True)
#     action     = db.Column(db.String(60),  nullable=True, index=True)
#
#     # Which record (optional)
#     record_id  = db.Column(db.Integer,     nullable=True)
#     record_ref = db.Column(db.String(100), nullable=True)
#
#     # Meta
#     ip_address = db.Column(db.String(45),  nullable=True)
#     extra_data = db.Column(db.Text,        nullable=True)   # JSON string
#
#     created_at = db.Column(
#         db.DateTime,
#         default=datetime.utcnow,
#         nullable=False,
#         index=True
#     )
#
#     # Relationship
#     user = db.relationship("User", backref="activity_logs", lazy=True)
#
#     def __repr__(self):
#         return (
#             f"<UserActivityLog "
#             f"user={self.user_id} "
#             f"module={self.module} "
#             f"action={self.action}>"
#         )
#
#
# # ─────────────────────────────────────────────────────────────────────────────
# # TABLE 3 : record_viewers
# #
# # Tracks which users currently have a specific record open.
# # Used for concurrent-edit DETECTION ONLY — no locking.
# # A viewer is considered active if last_seen_at is within IDLE_THRESHOLD.
# # ─────────────────────────────────────────────────────────────────────────────
#
# class RecordViewer(db.Model):
#
#     __tablename__ = "record_viewers"
#
#     id = db.Column(db.Integer, primary_key=True)
#
#     user_id = db.Column(
#         db.Integer,
#         db.ForeignKey("users.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True
#     )
#
#     module     = db.Column(db.String(60),  nullable=False)
#     record_id  = db.Column(db.Integer,     nullable=False)
#     record_ref = db.Column(db.String(100), nullable=True)
#
#     opened_at   = db.Column(db.DateTime, default=datetime.utcnow)
#     last_seen_at= db.Column(db.DateTime, default=datetime.utcnow, index=True)
#
#     # One row per (user, module, record) combination
#     __table_args__ = (
#         db.UniqueConstraint(
#             "user_id", "module", "record_id",
#             name="uq_record_viewer"
#         ),
#         db.Index(
#             "ix_record_viewers_module_record",
#             "module", "record_id"
#         ),
#     )
#
#     # Relationship
#     user = db.relationship("User", backref="record_views", lazy=True)
#
#     def __repr__(self):
#         return (
#             f"<RecordViewer "
#             f"user={self.user_id} "
#             f"module={self.module} "
#             f"record={self.record_id}>"
#         )
#
#
# # =============================================================================
# # INTEGRATION NOTE
# # =============================================================================
# #
# # Existing file : app/models/__init__.py
# #
# # Add these 3 lines at the end of that file:
# #
# #   from .user_activity_model import UserPresence
# #   from .user_activity_model import UserActivityLog
# #   from .user_activity_model import RecordViewer
# #
# # Then run:
# #   flask db migrate -m "add tracking tables"
# #   flask db upgrade
# #
# # =============================================================================
