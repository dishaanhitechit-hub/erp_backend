"""One backup run, the 5-minute tick, and the daily summary e-mail."""

import os
import shutil
import traceback
from datetime import datetime, timedelta

from . import __version__, backupset, emails, idle, naming, notify, retention, schedule
from . import state as st
from .remote import Remote, RemoteSet
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
    outage) into its folder, then apply retention on Drive: delete what is no
    longer kept and move sets into Weekly/ or Monthly/. Raises BackupError."""
    remote = Remote(settings)
    on_drive = remote.list_sets()
    for name, path in local_sets(settings):
        if os.path.exists(os.path.join(path, UPLOADED_MARK)):
            continue
        when = parse_set_id(name).astimezone(settings.tz)
        tier = "manual" if _trigger(path) == "MANUAL" else "daily"
        remote.upload_set(path, naming.drive_path(settings.label, tier, when), existing=on_drive)
        open(os.path.join(path, UPLOADED_MARK), "w").close()

    if settings.media_mode == "sync":
        remote.sync_media(settings.media_sources, newest_id)
        remote.prune_media_versions(now, settings.media_versions_days)

    kept = apply_retention(settings, remote, now)
    remote.cleanup_partials(now)
    write_remote_cache(settings, kept, now)

    if settings.heartbeat_remote:
        counts = {t: sum(1 for rs in kept if rs.tier == t) for t in naming.TIERS}
        newest = kept[-1].path if kept else None
        remote.write_heartbeat(settings.heartbeat_remote, {
            "last_success_id": newest_id,
            "last_success_at": now.isoformat(),
            "newest_on_drive": newest,
            "sets_on_drive": len(kept),
            "by_type": counts,
            "tool_version": __version__,
        })
        try:
            remote.write_text(_status_file(settings, "HOW-TO-RESTORE.txt"), restore_guide(settings))
        except BackupError as e:            # nice to have — never fail a backup for it
            log.warning("could not write HOW-TO-RESTORE.txt: %s", e)


def apply_retention(settings, remote, now):
    """Delete / move sets on Drive per retention.types. Returns the kept sets
    (RemoteSet, at their new paths), oldest first."""
    sets = remote.list_sets()
    by_path = {rs.path: rs for rs in sets}
    keep, delete = retention.types(
        [(rs.path, rs.when) for rs in sets], now, settings.tz,
        manual=[rs.path for rs in sets if rs.tier == "manual"],
        daily_days=settings.keep_daily_days, weekly=settings.keep_weekly,
        monthly=settings.keep_monthly, min_keep=settings.min_keep)
    for path in delete:
        log.info("retention: deleting %s from Google Drive", path)
        remote.delete_set(by_path[path])
    taken = set(keep)
    kept = []
    for path, tier in keep.items():
        rs = by_path[path]
        want = naming.drive_path(settings.label, tier, rs.when.astimezone(settings.tz))
        if want != path and want not in taken:
            remote.move(path, want)
            taken.discard(path)
            taken.add(want)
            rs = RemoteSet(want, want.rsplit("/", 1)[-1], naming.canonical_id(want.rsplit("/", 1)[-1]),
                           rs.when, tier)
        elif want != path:
            log.warning("retention: %s should be %s, but that name is taken — left in place", path, want)
        kept.append(rs)
    if delete or any(rs.path not in by_path for rs in kept):
        remote.remove_empty_folders()
    return sorted(kept, key=lambda r: r.when)


def _trigger(set_path):
    try:
        return backupset.load_manifest(set_path).get("trigger")
    except (OSError, ValueError):
        return None


def _status_file(settings, name):
    """`name` next to the heartbeat file (same plain, unencrypted folder)."""
    target = settings.heartbeat_remote
    if "/" in target.split(":", 1)[-1]:
        return target.rsplit("/", 1)[0] + "/" + name
    return target.split(":", 1)[0] + ":" + name


def restore_guide(settings):
    root = settings.remote
    return f"""ERP backups — how to find and restore one
==========================================

Folder: {root}   (written by erp_backup {__version__})

  Daily/<year-month>/   every backup of the last {settings.keep_daily_days} days
  Weekly/<year>/        the last backup of each finished week (last {settings.keep_weekly} weeks)
  Monthly/<year>/       the last backup of each finished month (last {settings.keep_monthly} months)
  Manual/<year>/        backups taken by hand (never deleted automatically)

Name of a backup:  {settings.label}_<type>_[week or month_]<date>_<time>
  e.g. {settings.label}_daily_2026-11-24_0215     = 24 Nov 2026, 02:15 (India time)
       {settings.label}_weekly_2026-W47_2026-11-23_2215
       {settings.label}_monthly_2026-11_2026-11-30_2215

The files inside (*.bin) are ENCRYPTED. They can only be read with the backup
encryption key that is kept offline (not on Google Drive, not in e-mail).

Restore (on the server, or a new server with rclone set up with that key):
  python -m erp_backup list --remote
  python -m erp_backup restore --from-remote --set {settings.label}_2026-11-24_0215 --target-db erp_db_restored
  (--set takes the date part of the name; the type in the folder name is optional)

Or use the PRAX Ops Console → Restore → Google Drive.
Never restore over the live database: restore into a new name, check it, then switch.
"""


def write_remote_cache(settings, sets, now):
    """List of sets on Google Drive, for the console (listing Drive is slow)."""
    from .util import write_json_atomic
    write_json_atomic(os.path.join(settings.local_dir, "remote_sets.json"),
                      {"at": now.isoformat(), "sets": [rs.as_dict() for rs in sets]})


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
    subject, html, text = emails.run_alert(settings, result)
    notify.send(settings, subject, text, html, category="backup_failure",
                urgent=result["status"] == "FAILED")


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
    subject, html, text = emails.overdue(settings, state, now)
    notify.send(settings, subject, text, html, category="backup_failure", urgent=True)
    state["overdue_alert_at"] = now.isoformat()


def _daily_summary(settings, state, now):
    today = now.date().isoformat()
    if now.hour < settings.summary_hour or state.get("summary_date") == today:
        return
    remote_count = about = remote_error = None
    if settings.remote:
        remote = Remote(settings)
        try:
            remote_count = len(remote.list_sets())
        except BackupError as e:
            remote_error = f"cannot list: {e}"[:200]
        about = remote.about()
    else:
        remote_error = "not configured — local only"
    subject, html, text = emails.daily(settings, state, now, len(local_sets(settings)),
                                       remote_count, about, remote_error)
    notify.send(settings, subject, text, html, category="backup_daily")
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
            on_drive = remote.list_sets()
            per = ", ".join(f"{t} {n}" for t in (*naming.TIERS, "legacy")
                            if (n := sum(1 for rs in on_drive if rs.tier == t)))
            lines.append(f"Sets on Google Drive: {len(on_drive)}" + (f"  ({per})" if per else ""))
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
