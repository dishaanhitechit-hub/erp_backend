"""Is the server idle right now? Every check must pass:

- few active database queries (pg_stat_activity, our own excluded)
- CPU load below BACKUP_IDLE_MAX_LOAD per core
- disk I/O wait below BACKUP_IDLE_MAX_IOWAIT %  (Linux only)
- no web request for BACKUP_IDLE_QUIET_MINUTES (mtime of BACKUP_ACCESS_LOG, if set)

A check that cannot be measured is skipped, not failed.
"""

import os
import time


def probe(settings):
    """(idle: bool, details: dict)."""
    details = {}
    busy = []

    active = _db_active(settings)
    details["db_active_queries"] = active
    if active is None:
        busy.append("database unreachable")
    elif active > settings.idle_max_db_active:
        busy.append(f"{active} active DB queries")

    cores = os.cpu_count() or 1
    load = os.getloadavg()[0] / cores
    details["load_per_core"] = round(load, 2)
    if load > settings.idle_max_load:
        busy.append(f"CPU load {load:.2f}/core")

    iowait = _iowait_percent()
    details["iowait_percent"] = iowait
    if iowait is not None and iowait > settings.idle_max_iowait:
        busy.append(f"I/O wait {iowait:.0f}%")

    if settings.access_log and os.path.exists(settings.access_log):
        quiet = (time.time() - os.path.getmtime(settings.access_log)) / 60
        details["minutes_since_last_request"] = round(quiet, 1)
        if quiet < settings.idle_quiet_minutes:
            busy.append(f"web request {quiet:.0f} min ago")

    details["busy_because"] = busy
    return not busy, details


def _db_active(settings):
    try:
        import psycopg2
        conn = psycopg2.connect(**settings.psycopg_kwargs())
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""SELECT count(*) FROM pg_stat_activity
                       WHERE state NOT IN ('idle') AND pid <> pg_backend_pid()
                         AND backend_type = 'client backend'""")
        return cur.fetchone()[0]
    except Exception:
        return None
    finally:
        conn.close()


def _cpu_times():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:]
    return [int(x) for x in parts]


def _iowait_percent(sample_seconds=1.0):
    if not os.path.exists("/proc/stat"):
        return None
    try:
        a = _cpu_times()
        time.sleep(sample_seconds)
        b = _cpu_times()
    except (OSError, ValueError):
        return None
    delta = [y - x for x, y in zip(a, b)]
    total = sum(delta) or 1
    return round(100.0 * delta[4] / total, 1)   # 5th field = iowait
