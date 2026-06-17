import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from app import create_app
from app.extensions import db
from app.utils.txn_tracker import TransactionTracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def notify_user(user_id, message):
    # plug in your email/SMS/push logic here
    logging.info(f"Notify user {user_id}: {message}")


def sweep_incomplete_transactions():
    app = create_app()
    with app.app_context():
        open_sessions = TransactionTracker.get_all_open()

        if not open_sessions:
            logging.info("No open transactions. Safe to proceed.")
            return

        for s in open_sessions:
            logging.warning(
                f"Incomplete txn: user={s.user_id}, "
                f"started={s.txn_started_at}, "
                f"desc={s.txn_description}"
            )

            notify_user(s.user_id, "Your incomplete work was cleared due to maintenance.")

            db.session.delete(s)

        db.session.commit()
        logging.info(f"Swept {len(open_sessions)} incomplete sessions.")


if __name__ == "__main__":
    sweep_incomplete_transactions()
