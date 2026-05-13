# =========================================================
# app/models/sub_module.py
# =========================================================

from app.extensions import db


class SubModule(db.Model):
    __tablename__ = "sub_modules"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    main_module_id = db.Column(
        db.Integer,
        db.ForeignKey("main_modules.id"),
        nullable=False
    )

    submodule_name = db.Column(
        db.String(100),
        nullable=False
    )

    main_module = db.relationship(
        "MainModule",
        backref="sub_modules"
    )