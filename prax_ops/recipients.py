"""Who receives which alert — one JSON file shared by every email sender.

File: $PRAX_ALERT_CONFIG  (default /srv/prax-config/alert_recipients.json)

    {
      "version": 1,
      "updated_at": "...", "updated_by": "...",
      "contacts": {"a@x.com": "Name", ...},
      "categories": {"backup_failure": ["a@x.com"], ...}
    }

It is a file, not a database table, on purpose: alerts must still go out
when the database is down. Every sender passes its old hard-coded list as
`fallback`, used when the file or the category is missing/unreadable, so a
broken file can never silence alerts. An empty list in the file is allowed
(it means: nobody gets this one) and the console warns about it.
"""

import json
import os
import re
import tempfile
from datetime import datetime

DEFAULT_PATH = "/srv/prax-config/alert_recipients.json"
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

# key → (group, label, description). Order = order shown in the console.
CATEGORIES = {
    "server_alert":        ("Server", "Server alerts (all)", "Every CPU / RAM / disk / temperature / service / database problem"),
    "server_critical":     ("Server", "New critical server alerts", "Extra copy when a NEW critical problem appears"),
    "server_recovery":     ("Server", "Recovered", "All problems resolved"),
    "server_daily":        ("Server", "Daily server report (08:00)", "24-hour health summary"),
    "server_migration":    ("Server", "Database migration", "Migration detected, or `flask db upgrade` failed in a deploy"),
    "server_startup":      ("Server", "Server started", "Server booted / restarted"),
    "backup_failure":      ("Backup", "Backup problems", "Backup failed, only saved locally, or no backup for 12 hours"),
    "backup_daily":        ("Backup", "Daily backup report (09:00)", "Runs, sizes, disk and Drive usage"),
    "backup_restore_test": ("Backup", "Weekly restore test", "Result of the Sunday restore test"),
    "console_activity":    ("Backup", "Restore / switch actions", "Someone restored or switched the live database in the console"),
    "monthly_finance":      ("Monthly reports", "Finance", "MAIL_RECIPIENT_FINANCE"),
    "monthly_hr":           ("Monthly reports", "HR", "MAIL_RECIPIENT_HR"),
    "monthly_billing":      ("Monthly reports", "Billing", "MAIL_RECIPIENT_BILLING"),
    "monthly_project":      ("Monthly reports", "Project", "MAIL_RECIPIENT_PROJECT"),
    "monthly_project_mgmt": ("Monthly reports", "Project management", "MAIL_RECIPIENT_PROJECT_MGMT"),
    "monthly_resources":    ("Monthly reports", "Resources", "MAIL_RECIPIENT_RESOURCES"),
    "monthly_master":       ("Monthly reports", "Master", "MAIL_RECIPIENT_MASTER"),
    "monthly_company":      ("Monthly reports", "Company", "MAIL_RECIPIENT_COMPANY"),
}


def path():
    return os.getenv("PRAX_ALERT_CONFIG") or DEFAULT_PATH


def split_emails(raw):
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = re.split(r"[,;\s]+", str(raw))
    out = []
    for e in items:
        e = str(e).strip().lower()
        if e and e not in out:
            out.append(e)
    return out


def load(file_path=None):
    """The whole config dict, or None when missing/unreadable."""
    try:
        with open(file_path or path()) as f:
            data = json.load(f)
        return data if isinstance(data.get("categories"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def get(category, fallback=None, file_path=None):
    """Recipients for one alert type; `fallback` when not configured."""
    data = load(file_path)
    if data is not None and category in data["categories"]:
        valid = [e for e in split_emails(data["categories"][category]) if EMAIL_RE.match(e)]
        return valid
    return split_emails(fallback)


def validate(data):
    """List of problems with a config dict about to be saved (empty = OK)."""
    problems = []
    cats = data.get("categories")
    if not isinstance(cats, dict):
        return ["categories missing"]
    for key, emails in cats.items():
        if key not in CATEGORIES:
            problems.append(f"unknown alert type: {key}")
            continue
        if not isinstance(emails, list):
            problems.append(f"{key}: must be a list")
            continue
        for e in emails:
            if not EMAIL_RE.match(str(e).strip()):
                problems.append(f"{key}: not an email address: {e}")
    contacts = data.get("contacts", {})
    if not isinstance(contacts, dict):
        problems.append("contacts must be an object")
    return problems


def save(data, updated_by, file_path=None):
    """Validate and write atomically. Returns the saved dict. Raises ValueError."""
    problems = validate(data)
    if problems:
        raise ValueError("; ".join(problems))
    clean = {
        "version": 1,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_by": updated_by,
        "contacts": {k.strip().lower(): str(v).strip()[:80]
                     for k, v in (data.get("contacts") or {}).items() if EMAIL_RE.match(k.strip())},
        "categories": {k: split_emails(v) for k, v in data["categories"].items()},
    }
    target = file_path or path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".recipients.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(clean, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return clean


def seed(fallbacks, updated_by="setup", file_path=None):
    """Create the file from today's hard-coded/env lists (only if missing)."""
    target = file_path or path()
    if os.path.exists(target):
        return load(target)
    cats = {k: split_emails(fallbacks.get(k)) for k in CATEGORIES}
    return save({"contacts": {}, "categories": cats}, updated_by, target)
