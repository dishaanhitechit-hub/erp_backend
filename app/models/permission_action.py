# =========================================================
# app/models/permission_action.py
# =========================================================

from app.extensions import db


class PermissionAction(db.Model):
    __tablename__ = "permission_actions"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    action_name = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )