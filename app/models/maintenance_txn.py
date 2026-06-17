from app.extensions import db
from datetime import datetime


class MaintenanceOpenTxn(db.Model):
    __tablename__ = "maintenance_open_txn"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    txn_description = db.Column(db.String(255), nullable=True)
    txn_started_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="open_txns")
