"""One backup run, the 5-minute tick, and the daily summary e-mail."""

import os
import shutil
import traceback
from datetime import datetime, timedelta

from . import backupset, idle, notify, retention, schedule
from . import state as st
from .remote import Remote
from .util import BackupError, Lock, human_bytes, log, parse_set_id

UPLOADED_MARK = ".uploaded"   # local marker: this set is safely on Google Drive


def lock_for(settings):
    return Lock(os.path.join(settings.local_dir, "backup.lock"))


# ── one run ─────────────────────────────────────────────────────────────────

def run_backup(settings, trigger, state, now=None):
    """Create a set, push it off-site, apply retention, alert on problems.
    Mutates and saves `state`. Returns the result dict."""
    now = (now or datetime.now(settings.tz)).replace(microsecond=0)
    today = now.date().isoformat()
    result = {"backup_id": None, "trigger": trigger, "status": "FAILED",
              "started_at": now.isoformat(), "warnings": [], "uploaded": False}
    want_plain = (settings.plain_sql_weekday == now.weekday()
                  and state.get("last_plain_sql_date") != today)
    try:
        set_path, manifest = backupset.create(settings, trigger, now=now, want_plain_sql=want_plain)
        result.update(
            backup_id=manifest["backup_id"],
            db_bytes=manifest["database"]["dump_bytes"],
            media_bytes=manifest["media"]["total_bytes"],
            media_files=manifest["media"]["file_count"],
            warnings=list(manifest["warnings"]),
        )
        if want_plain and os.path.exists(os.path.join(set_path, "db.sql.gz")):
            state["last_plain_sql_date"] = today

        offsite_error = None
        if settings.remote:
            try:
                push_offsite(settings, now, manifest["backup_id"])
                result["uploaded"] = True
            except BackupError as e:
                offsite_error = str(e)
            except Exception as e:  # network libs etc. — keep the local set
                offsite_error = f"{type(e).__name__}: {e}"
        prune_local(settings)

        if offsite_error:
            result["status"] = "PARTIAL"
            result["error"] = f"saved on the backup disk, but Google Drive upload failed: {offsite_error}"
        else:
            result["status"] = "SUCCESS"
    except BackupError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}"

    result["finished_at"] = datetime.now(settings.tz).replace(microsecond=0).isoformat()
    st.record_run(state, result)
    st.save(settings, state)
    log.info("backup %s: %s %s", result["backup_id"], result["status"], result.get("error") or "")
    _alert_for(settings, result)
    return result


def push_offsite(settings, now, newest_id):
    """Upload every local set not yet on Drive (catches up after an internet
    outage), then apply retention on Drive. Raises BackupError on failure."""
    remote = Remote(settings)
    for name, path in local_sets(settings):
        if os.path.exists(os.path.join(path, UPLOADED_MARK)):
            continue
        remote.upload_set(path, name)
        open(os.path.join(path, UPLOADED_MARK), "w").close()

    if settings.media_mode == "sync":
        remote.sync_media(settings.media_sources, newest_id)
        remote.prune_media_versions(now, settings.media_versions_days)

    names = [n for n in remote.list_sets() if parse_set_id(n)]
    keep, delete = retention.plan([(n, parse_set_id(n)) for n in names], now, settings.tz,
                                  settings.keep_daily_days, settings.keep_weekly,
                                  settings.keep_monthly, settings.min_keep)
    for name in delete:
        log.info("retention: deleting %s from Google Drive", name)
        remote.delete_set(name)
    remote.cleanup_partials(now)

    if settings.heartbeat_remote:
        remote.write_heartbeat(settings.heartbeat_remote, {
            "last_success_id": newest_id,
            "last_success_at": now.isoformat(),
            "sets_on_drive": len(keep),
        })


def local_sets(settings):
    """[(name, path)] of finished local sets, oldest first."""
    root = backupset.sets_dir(settings)
    if not os.path.isdir(root):
        return []
    names = sorted((n for n in os.listdir(root) if parse_set_id(n)), key=parse_set_id)
    return [(n, os.path.join(root, n)) for n in names]


def prune_local(settings):
    """Keep the newest BACKUP_LOCAL_KEEP sets on the backup disk. A set that
    is not yet on Google Drive is never deleted."""
    sets = local_sets(settings)
    excess = sets[:-settings.local_keep] if settings.local_keep > 0 else []
    for name, path in excess:
        if settings.remote and not os.path.exists(os.path.join(path, UPLOADED_MARK)):
            continue
        log.info("removing old local set %s", name)
        shutil.rmtree(path, ignore_errors=True)
    root = backupset.sets_dir(settings)
    if os.path.isdir(root):
        for n in os.listdir(root):                      # leftovers from a crash
            if n.endswith(".partial"):
                shutil.rmtree(os.path.join(root, n), ignore_errors=True)


def _alert_for(settings, result):
    if result["status"] == "SUCCESS":
        return
    if result["status"] == "PARTIAL":
        subject = f"WARNING — backup {result['backup_id']} only on local disk"
    else:
        subject = "FAILED — backup did not complete"
        if "CORRUPTION" in (result.get("error") or ""):
            subject = "URGENT — possible DATABASE CORRUPTION, backup failed"
    body = (f"Backup:   {result['backup_id'] or '(not created)'}\n"
            f"Trigger:  {result['trigger']}\n"
            f"Started:  {result['started_at']}\n"
            f"Status:   {result['status']}\n\n"
            f"Problem:\n{result.get('error')}\n\n")
    if result["warnings"]:
        body += "Warnings:\n" + "\n".join(f" - {w}" for w in result["warnings"]) + "\n\n"
    body += ("The tool retries automatically. Old backups are NOT deleted while runs fail.\n"
             "On the server:  sudo -u erpbackup /opt/erp_backend/.venv/bin/python -m erp_backup status\n")
    notify.send(settings, subject, body)


# ── every 5 minutes ─────────────────────────────────────────────────────────

def tick(settings, now=None):
    lock = lock_for(settings)
    if not lock.acquire():
        log.info("another backup is running — skipping this tick")
        return None
    try:
        now = (now or datetime.now(settings.tz)).replace(microsecond=0)
        state = st.load(settings)

        if schedule.active_window(now, settings.windows):
            is_idle, details = idle.probe(settings)
            if is_idle:
                state.setdefault("idle_since", now.isoformat())
            else:
                state.pop("idle_since", None)
            state["last_idle_probe"] = details
        else:
            state.pop("idle_since", None)

        decision = schedule.decide(now, settings, st.dt(state, "last_success_at"),
                                   st.dt(state, "last_attempt_at"),
                                   state.get("last_attempt_ok", True), st.dt(state, "idle_since"))
        state["last_decision"] = {"at": now.isoformat(), "run": decision.run, "reason": decision.reason}
        st.save(settings, state)
        log.info("tick: %s (%s)", "RUN " + decision.trigger if decision.run else "wait", decision.reason)

        if decision.run:
            run_backup(settings, decision.trigger, state, now=now)
            state.pop("idle_since", None)

        _overdue_alarm(settings, state, now)
        _daily_summary(settings, state, now)
        st.save(settings, state)
        return decision
    finally:
        lock.release()


def _overdue_alarm(settings, state, now):
    last = st.dt(state, "last_success_at")
    limit = timedelta(hours=settings.max_gap_hours)
    if last and now - last <= limit:
        return
    sent = st.dt(state, "overdue_alert_at")
    if sent and now - sent < timedelta(hours=6):
        return
    when = f"{last:%d %b %H:%M}" if last else "never"
    notify.send(settings, "ALERT — no successful backup in the last "
                f"{settings.max_gap_hours:g} hours",
                f"Last successful backup: {when}\nLast error: {state.get('last_error')}\n\n"
                "Data entered since then is NOT protected. Check the server.\n")
    state["overdue_alert_at"] = now.isoformat()


def _daily_summary(settings, state, now):
    today = now.date().isoformat()
    if now.hour < settings.summary_hour or state.get("summary_date") == today:
        return
    notify.send(settings, f"Daily backup report {now:%d %b %Y}", summary_text(settings, state, now))
    state["summary_date"] = today


def summary_text(settings, state, now):
    lines = []
    last = st.dt(state, "last_success_at")
    lines.append(f"Last successful backup: {state.get('last_success_id') or 'never'}"
                 + (f"  ({(now - last).total_seconds() / 3600:.1f} h ago)" if last else ""))
    lines.append("")
    lines.append("Runs in the last 24 hours:")
    cutoff = now - timedelta(hours=24)
    recent = [h for h in state.get("history", [])
              if h.get("started_at") and datetime.fromisoformat(h["started_at"]) >= cutoff]
    for h in recent:
        lines.append(f"  {h['started_at'][:16]}  {h['status']:<8} {h['trigger']:<9} "
                     f"DB {human_bytes(h.get('db_bytes'))}, media {human_bytes(h.get('media_bytes'))} "
                     f"({h.get('media_files') or 0} files), on Drive: {'yes' if h.get('uploaded') else 'no'}")
        for w in h.get("warnings") or []:
            lines.append(f"      ! {w}")
        if h.get("error"):
            lines.append(f"      ERROR: {h['error'][:300]}")
    if not recent:
        lines.append("  (none)")

    usage = shutil.disk_usage(settings.local_dir)
    pct = 100 * usage.used / usage.total
    lines += ["", f"Backup disk {settings.local_dir}: {human_bytes(usage.free)} free ({pct:.0f}% used)"
              + ("  ← WARNING: over 80%" if pct > 80 else "")]
    lines.append(f"Sets on backup disk: {len(local_sets(settings))}")
    if settings.remote:
        remote = Remote(settings)
        try:
            lines.append(f"Sets on Google Drive: {len([n for n in remote.list_sets() if parse_set_id(n)])}")
        except BackupError as e:
            lines.append(f"Google Drive: cannot list ({e})")
        about = remote.about()
        if about and about.get("total"):
            dpct = 100 * about.get("used", 0) / about["total"]
            lines.append(f"Google Drive: {human_bytes(about.get('used'))} of {human_bytes(about['total'])} "
                         f"used ({dpct:.0f}%)" + ("  ← WARNING: over 80%" if dpct > 80 else ""))
    else:
        lines.append("Google Drive: NOT CONFIGURED (BACKUP_REMOTE empty) — backups are local only")
    v = state.get("last_verify")
    if v:
        lines.append(f"Last restore test: {v.get('at', '')[:16]} {v.get('status')} ({v.get('backup_id')})")
    else:
        lines.append("Last restore test: never")
    return "\n".join(lines) + "\n"
