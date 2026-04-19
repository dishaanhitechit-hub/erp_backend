# app/models/designation.py

from app.extensions import db

class Designation(db.Model):
    __tablename__ = "designations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
