"""Which backup sets to keep — pure logic (unit-tested).

Default policy (BACKUP_KEEP_*):
  - every set from the last 7 days            (daily: rolling, the 8th day drops off)
  - the newest set of each of the last 4 weeks (weekly)
  - the newest set of each of the last 6 months (monthly)
  - and never fewer than the newest 3 sets, whatever their age (safety)

Retention only runs right after a successful backup, so when backups keep
failing (e.g. the database is corrupted) nothing old is ever deleted.
"""

from datetime import timedelta


def plan(sets, now, tz, daily_days=7, weekly=4, monthly=6, min_keep=3):
    """sets: iterable of (name, aware datetime). Returns (keep: dict name->reason, delete: list)."""
    items = sorted(sets, key=lambda s: s[1], reverse=True)
    keep = {}

    for i, (name, when) in enumerate(items):
        if i < min_keep:
            keep.setdefault(name, "newest")
        if now - when < timedelta(days=daily_days):
            keep.setdefault(name, "daily")

    def newest_per_bucket(bucket_of, limit, reason):
        seen = []
        for name, when in items:
            b = bucket_of(when.astimezone(tz))
            if b in seen:
                continue
            if len(seen) >= limit:
                break
            seen.append(b)
            keep.setdefault(name, reason)

    if weekly > 0:
        newest_per_bucket(lambda d: d.isocalendar()[:2], weekly, "weekly")
    if monthly > 0:
        newest_per_bucket(lambda d: (d.year, d.month), monthly, "monthly")

    delete = [name for name, _ in items if name not in keep]
    return keep, delete
