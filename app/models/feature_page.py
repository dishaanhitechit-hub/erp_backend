# =========================================================
# app/models/feature_page.py
# =========================================================

from app.extensions import db


class FeaturePage(db.Model):
    __tablename__ = "feature_pages"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    submodule_id = db.Column(
        db.Integer,
        db.ForeignKey("sub_modules.id"),
        nullable=False
    )

    page_name = db.Column(
        db.String(100),
        nullable=False
    )

    page_code = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    route_path = db.Column(
        db.String(255)
    )

    is_menu_visible = db.Column(
        db.Boolean,
        default=True
    )

    sort_order = db.Column(
        db.Integer,
        default=0
    )

    submodule = db.relationship(
        "SubModule",
        backref="feature_pages"
    )