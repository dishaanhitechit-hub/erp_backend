from datetime import datetime
from app.extensions import db
from app.models.maintenance_txn import MaintenanceOpenTxn


class TransactionTracker:

    @staticmethod
    def mark_open(user_id: int, description: str = ""):
        """Call when user STARTS a multi-step operation"""
        # Remove any stale open record first
        db.session.query(MaintenanceOpenTxn).filter_by(user_id=user_id).delete()

        record = MaintenanceOpenTxn(
            user_id=user_id,
            txn_description=description,
            txn_started_at=datetime.utcnow()
        )
        db.session.add(record)
        db.session.commit()

    @staticmethod
    def mark_closed(user_id: int):
        """Call when user COMPLETES or CANCELS the operation"""
        db.session.query(MaintenanceOpenTxn).filter_by(user_id=user_id).delete()
        db.session.commit()

    @staticmethod
    def get_all_open():
        """Get all users with incomplete work right now"""
        return db.session.query(MaintenanceOpenTxn).all()
