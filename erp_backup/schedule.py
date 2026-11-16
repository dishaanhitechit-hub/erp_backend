"""When to run a backup — pure logic, no I/O (unit-tested).

`tick` is called every 5 minutes. Rules, in order:

1. A run failed less than BACKUP_RETRY_MINUTES ago → wait before retrying.
2. No successful backup for (BACKUP_MAX_GAP_HOURS - 30 min) → run now, any time
   of day (trigger OVERDUE). This is what guarantees "at most 12 h of data lost".
3. Outside every backup window → nothing to do.
4. This window already has a success, or one ran in the last
   BACKUP_SKIP_IF_RECENT_HOURS → nothing to do.
5. Window is about to close → run even if the server is busy (trigger DEADLINE).
6. Server has been idle for BACKUP_IDLE_MINUTES → run (trigger IDLE).
7. Otherwise keep waiting for the server to go idle.
"""

from dataclasses import dataclass
from datetime import timedelta

OVERDUE_HEADROOM = timedelta(minutes=30)


@dataclass
class Decision:
    run: bool
    trigger: str = ""      # IDLE | DEADLINE | OVERDUE
    reason: str = ""


def active_window(now, windows):
    """(window, start, end) of the window `now` is in, or None."""
    for w in windows:
        start = now.replace(hour=w.start.hour, minute=w.start.minute, second=0, microsecond=0)
        end = now.replace(hour=w.end.hour, minute=w.end.minute, second=0, microsecond=0)
        if w.end <= w.start:                    # crosses midnight, e.g. 22:00-04:00
            if now.time() >= w.start:
                end += timedelta(days=1)
            else:
                start -= timedelta(days=1)
        if start <= now < end:
            return w, start, end
    return None


def decide(now, settings, last_success, last_attempt, last_attempt_ok, idle_since):
    max_gap = timedelta(hours=settings.max_gap_hours)

    if last_attempt and not last_attempt_ok and now - last_attempt < timedelta(minutes=settings.retry_minutes):
        return Decision(False, reason="last run failed — waiting before retry")

    if last_success is None:
        return Decision(True, "OVERDUE", "no successful backup yet")
    if now - last_success >= max_gap - OVERDUE_HEADROOM:
        return Decision(True, "OVERDUE", f"last success {_ago(now - last_success)} ago")

    win = active_window(now, settings.windows)
    if not win:
        return Decision(False, reason="outside backup windows")
    window, start, end = win
    if last_success >= start:
        return Decision(False, reason=f"window {window} already backed up")
    if now - last_success < timedelta(hours=settings.skip_if_recent_hours):
        return Decision(False, reason=f"recent backup {_ago(now - last_success)} ago")

    if now >= end - timedelta(minutes=settings.deadline_margin_minutes):
        return Decision(True, "DEADLINE", f"window {window} closing, server never went idle")
    if idle_since and now - idle_since >= timedelta(minutes=settings.idle_minutes):
        return Decision(True, "IDLE", f"server idle since {idle_since:%H:%M}")
    return Decision(False, reason=f"in window {window}, waiting for server to be idle")


def next_window_start(now, windows):
    """When the next backup window opens (now, if inside one)."""
    if active_window(now, windows):
        return now
    best = None
    for w in windows:
        start = now.replace(hour=w.start.hour, minute=w.start.minute, second=0, microsecond=0)
        if start <= now:
            start += timedelta(days=1)
        best = start if best is None or start < best else best
    return best


def _ago(delta):
    mins = int(delta.total_seconds() // 60)
    return f"{mins // 60}h{mins % 60:02d}m"
