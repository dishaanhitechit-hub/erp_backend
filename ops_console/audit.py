"""Audit log: one JSON line per console action (who, when, from where, what)."""

import json
import os
from datetime import datetime


def write_audit(cfg, user, action, ip, details=None):
    os.makedirs(cfg.data_dir, exist_ok=True)
    entry = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "user": user,
             "ip": ip, "action": action, "details": details or {}}
    with open(cfg.audit_file, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_audit(cfg, limit=300):
    try:
        with open(cfg.audit_file) as f:
            lines = f.readlines()[-limit:]
    except FileNotFoundError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def notify_action(settings, action, user, details):
    """Email the 'Restore / switch actions' recipients. Never raises."""
    try:
        from erp_backup import emails, notify
        subject, html, text = emails.console_action(action, user, {k: str(v)[:300] for k, v in details.items()})
        notify.send(settings, subject, text, html, category="console_activity")
    except Exception:
        pass
