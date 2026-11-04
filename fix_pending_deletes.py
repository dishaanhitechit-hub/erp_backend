"""
One-time fix: process all stuck PENDING delete requests.

Run with:
    python fix_pending_deletes.py

For each PENDING delete request whose blockers are now gone,
this script will delete the record and mark the request COMPLETED.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.extensions import db
from app.models.delete_request import DeleteRequest
from datetime import datetime

from app.modules.delete_manager.service import (
    _check_children,
    _do_delete_record,
    DEPENDENCY_MAP,
)

app = create_app()

with app.app_context():
    pending = DeleteRequest.query.filter_by(status="PENDING").all()
    print(f"Found {len(pending)} PENDING delete requests.\n")

    for dr in pending:
        config = DEPENDENCY_MAP.get(dr.module_code)
        if not config:
            print(f"  [SKIP] DR#{dr.id} — unknown module {dr.module_code}")
            continue

        blocking = _check_children(dr.module_code, dr.record_id, config)

        if blocking:
            docs = ", ".join(b["doc_no"] for b in blocking[:5])
            print(f"  [BLOCKED] DR#{dr.id} {dr.module_code} #{dr.record_id} ({dr.record_no}) — still blocked by: {docs}")
            continue

        # Check if the record even still exists
        model_class = config["model_class"]
        record = model_class.query.get(dr.record_id)
        if not record:
            print(f"  [ALREADY GONE] DR#{dr.id} {dr.module_code} #{dr.record_id} — record missing, marking COMPLETED")
            dr.status       = "COMPLETED"
            dr.completed_at = datetime.utcnow()
            db.session.commit()
            continue

        # Delete it now
        try:
            _do_delete_record(dr.module_code, dr.record_id, config)
            dr.status             = "COMPLETED"
            dr.completed_at       = datetime.utcnow()
            dr.blocked_by_modules = "[]"
            dr.blocked_by_docs    = ""
            db.session.commit()
            print(f"  [DELETED] DR#{dr.id} {dr.module_code} {dr.record_no} — deleted and marked COMPLETED")
        except Exception as e:
            db.session.rollback()
            print(f"  [ERROR]   DR#{dr.id} {dr.module_code} {dr.record_no} — {e}")

    print("\nDone.")
