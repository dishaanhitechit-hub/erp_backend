"""Small JSON state file on the backup disk (kept outside the database on
purpose: it must still work when the database is broken)."""

import json
import os
from datetime import datetime

from .util import write_json_atomic

HISTORY_LEN = 60


def _path(settings):
    return os.path.join(settings.local_dir, "state.json")


def load(settings):
    try:
        with open(_path(settings)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(settings, state):
    os.makedirs(settings.local_dir, exist_ok=True)
    write_json_atomic(_path(settings), state)


def dt(state, key):
    raw = state.get(key)
    return datetime.fromisoformat(raw) if raw else None


def record_run(state, result):
    """Add a finished run to the state (result = dict from runner)."""
    state["last_attempt_at"] = result["started_at"]
    state["last_attempt_ok"] = result["status"] != "FAILED"
    state["last_error"] = result.get("error")
    if result["status"] != "FAILED":
        state["last_success_at"] = result["started_at"]
        state["last_success_id"] = result["backup_id"]
        state.pop("overdue_alert_at", None)
    hist = state.setdefault("history", [])
    hist.append({k: result.get(k) for k in
                 ("backup_id", "trigger", "status", "started_at", "finished_at",
                  "db_bytes", "media_bytes", "media_files", "uploaded", "error", "warnings")})
    del hist[:-HISTORY_LEN]
    return state
