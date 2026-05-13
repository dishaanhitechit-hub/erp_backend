# =========================================================
# OPTIONAL USER OVERRIDE
# app/models/project_user_permission.py
# =========================================================

from app.extensions import db


class ProjectUserPermission(db.Model):
    __tablename__ = "project_user_permissions"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    project_user_role_id = db.Column(
        db.Integer,
        db.ForeignKey("project_user_roles.id"),
        nullable=False
    )

    page_id = db.Column(
        db.Integer,
        db.ForeignKey("feature_pages.id"),
        nullable=False
    )

    action_id = db.Column(
        db.Integer,
        db.ForeignKey("permission_actions.id"),
        nullable=False
    )

    allowed = db.Column(
        db.Boolean,
        default=True
    )

    project_user_role = db.relationship(
        "ProjectUserRole"
    )

    page = db.relationship(
        "FeaturePage"
    )

    action = db.relationship(
        "PermissionAction"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "project_user_role_id",
            "page_id",
            "action_id",
            name="uq_project_user_permission"
        ),
    )