"""Which backup sets to keep, and in which folder — pure logic (unit-tested).

Default policy (BACKUP_KEEP_*):
  - every set from the last 7 days            (daily: rolling, the 8th day drops off)
  - the newest set of each of the last 4 weeks (weekly)
  - the newest set of each of the last 6 months (monthly)
  - and never fewer than the newest 3 sets, whatever their age (safety)
  - manual sets (`python -m erp_backup run`) are never deleted automatically

Folder on Google Drive (`types`): a set moves to Weekly/ once its week is
over and it was that week's last backup, and to Monthly/ once its month is
over and it was that month's last backup (Monthly wins over Weekly). Everything
else stays in Daily/. A finished week or month never gets a newer set, so a
set is moved at most twice and never back.

Retention only runs right after a successful backup, so when backups keep
failing (e.g. the database is corrupted) nothing old is ever deleted.
"""

from datetime import timedelta

ORDER = ("newest", "daily", "weekly", "monthly")


def reasons(sets, now, tz, daily_days=7, weekly=4, monthly=6, min_keep=3):
    """sets: iterable of (name, aware datetime). Returns {name: set of reasons} for sets to keep."""
    items = sorted(sets, key=lambda s: s[1], reverse=True)
    out = {}

    for i, (name, when) in enumerate(items):
        if i < min_keep:
            out.setdefault(name, set()).add("newest")
        if now - when < timedelta(days=daily_days):
            out.setdefault(name, set()).add("daily")

    def newest_per_bucket(bucket_of, limit, reason):
        seen = []
        for name, when in items:
            b = bucket_of(when.astimezone(tz))
            if b in seen:
                continue
            if len(seen) >= limit:
                break
            seen.append(b)
            out.setdefault(name, set()).add(reason)

    if weekly > 0:
        newest_per_bucket(_week, weekly, "weekly")
    if monthly > 0:
        newest_per_bucket(_month, monthly, "monthly")
    return out, items


def plan(sets, now, tz, daily_days=7, weekly=4, monthly=6, min_keep=3):
    """Returns (keep: dict name->reason, delete: list)."""
    why, items = reasons(sets, now, tz, daily_days, weekly, monthly, min_keep)
    keep = {name: next(r for r in ORDER if r in rs) for name, rs in why.items()}
    delete = [name for name, _ in items if name not in keep]
    return keep, delete


def types(sets, now, tz, manual=(), daily_days=7, weekly=4, monthly=6, min_keep=3):
    """Like plan(), but says which folder each kept set belongs in.

    sets:   iterable of (name, aware datetime)
    manual: names of manual sets — always kept, always 'manual', not counted for the rest
    Returns (keep: dict name -> 'daily'|'weekly'|'monthly'|'manual', delete: list)."""
    manual = set(manual)
    sets = list(sets)
    auto = [(n, w) for n, w in sets if n not in manual]
    why, items = reasons(auto, now, tz, daily_days, weekly, monthly, min_keep)
    local_now = now.astimezone(tz)
    keep = {}
    for name, when in items:
        rs = why.get(name)
        if not rs:
            continue
        local = when.astimezone(tz)
        if "monthly" in rs and _month(local) < _month(local_now):
            keep[name] = "monthly"
        elif "weekly" in rs and _week(local) < _week(local_now):
            keep[name] = "weekly"
        else:
            keep[name] = "daily"
    for name, _ in sets:
        if name in manual:
            keep[name] = "manual"
    delete = [name for name, _ in items if name not in keep]
    return keep, delete


def _week(d):
    return d.isocalendar()[:2]


def _month(d):
    return (d.year, d.month)
