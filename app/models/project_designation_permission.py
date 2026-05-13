# =========================================================
# app/models/project_designation_permission.py
# =========================================================

from app.extensions import db


class ProjectDesignationPermission(db.Model):
    __tablename__ = "project_designation_permissions"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id"),
        nullable=False
    )

    designation_id = db.Column(
        db.Integer,
        db.ForeignKey("designations.id"),
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

    project = db.relationship(
        "Project"
    )

    designation = db.relationship(
        "Designation"
    )

    page = db.relationship(
        "FeaturePage"
    )

    action = db.relationship(
        "PermissionAction"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "project_id",
            "designation_id",
            "page_id",
            "action_id",
            name="uq_project_designation_permission"
        ),
    )