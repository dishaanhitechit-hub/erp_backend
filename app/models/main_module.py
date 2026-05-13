# =========================================================
# app/models/main_module.py
# =========================================================

from app.extensions import db


class MainModule(db.Model):
    __tablename__ = "main_modules"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    module_name = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    icon = db.Column(
        db.String(100)
    )