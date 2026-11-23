"""Backup set names and the folder layout on Google Drive (pure logic, unit-tested).

A set's id (local folder name, manifest `backup_id`, what you pass to --set):

    PRAX-ERP_2026-11-24_0215                    <label>_<date>_<HHMM>, server time zone (IST)

On Google Drive the folder also says what kind of backup it is, inside a
folder per type:

    Daily/2026-11/PRAX-ERP_daily_2026-11-24_0215/
    Weekly/2026/PRAX-ERP_weekly_2026-W47_2026-11-23_2215/      (ISO week)
    Monthly/2026/PRAX-ERP_monthly_2026-11_2026-11-30_2215/
    Manual/2026/PRAX-ERP_manual_2026-11-24_1530/               (python -m erp_backup run)

Sets made before 1.2.0 are named erp_<env>_<YYYYmmddTHHMMSS+zzzz> and lived in
sets/ — they are still recognised everywhere.
"""

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
TIERS = ("daily", "weekly", "monthly", "manual")
TIER_FOLDERS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "manual": "Manual"}
FOLDER_TIERS = {v: k for k, v in TIER_FOLDERS.items()}

LEGACY_RE = re.compile(r"^erp_(?P<env>[A-Za-z0-9-]+)_(?P<ts>\d{8}T\d{6}[+-]\d{4})$")
NAME_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9-]*)_"
    r"(?:(?P<tier>daily|weekly|monthly|manual)_)?"
    r"(?:(?P<period>\d{4}-W\d{2}|\d{4}-\d{2})_)?"
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<hm>\d{4})$")


def default_tz():
    return ZoneInfo(os.getenv("BACKUP_TIMEZONE") or os.getenv("MAIL_TIMEZONE") or "Asia/Kolkata")


def set_id_for(label, when):
    """Id of a new set taken at `when` (an aware datetime in the server's time zone)."""
    return f"{label}_{when:%Y-%m-%d_%H%M}"


def parse_set_id(name, tz=None):
    """When the set was taken (aware datetime), or None if `name` is not a set.
    Accepts ids, Drive folder names (with type) and pre-1.2.0 names."""
    m = NAME_RE.match(name or "")
    if m:
        try:
            naive = datetime.strptime(f"{m['date']} {m['hm']}", "%Y-%m-%d %H%M")
        except ValueError:
            return None
        return naive.replace(tzinfo=tz or default_tz())
    m = LEGACY_RE.match(name or "")
    if m:
        return datetime.strptime(m["ts"], "%Y%m%dT%H%M%S%z")
    return None


def canonical_id(name):
    """The set id inside a Drive folder name: PRAX-ERP_weekly_2026-W47_2026-11-23_2215
    → PRAX-ERP_2026-11-23_2215. Pre-1.2.0 names are returned unchanged."""
    m = NAME_RE.match(name or "")
    if m:
        return f"{m['label']}_{m['date']}_{m['hm']}"
    return name if LEGACY_RE.match(name or "") else None


def tier_of_name(name):
    m = NAME_RE.match(name or "")
    return m["tier"] if m else None


def drive_name(label, tier, when):
    if tier == "weekly":
        year, week, _ = when.isocalendar()
        return f"{label}_weekly_{year}-W{week:02d}_{when:%Y-%m-%d_%H%M}"
    if tier == "monthly":
        return f"{label}_monthly_{when:%Y-%m}_{when:%Y-%m-%d_%H%M}"
    if tier not in TIERS:
        raise ValueError(f"unknown backup type {tier!r}")
    return f"{label}_{tier}_{when:%Y-%m-%d_%H%M}"


def drive_folder(tier, when):
    if tier == "daily":
        return f"Daily/{when:%Y-%m}"
    if tier == "weekly":
        return f"Weekly/{when.isocalendar()[0]}"
    return f"{TIER_FOLDERS[tier]}/{when:%Y}"


def drive_path(label, tier, when):
    """Path of a set under BACKUP_REMOTE, e.g. Daily/2026-11/PRAX-ERP_daily_2026-11-24_0215."""
    return f"{drive_folder(tier, when)}/{drive_name(label, tier, when)}"
