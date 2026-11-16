"""Backup alert emails in the PRAX style. Each builder returns
(subject, html, text) — the text part is for mail apps without HTML."""

import shutil
from datetime import datetime, timedelta

from prax_ops import email_html as E

from .util import human_bytes

TITLE = "PRAX ERP Backup"


def _when(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y %H:%M")
    except ValueError:
        return iso


# ── one failed / partial run ────────────────────────────────────────────────

def run_alert(settings, result):
    corruption = "CORRUPTION" in (result.get("error") or "")
    if result["status"] == "PARTIAL":
        level, title = "warning", "Backup saved locally only"
        subject = f"⚠️ PRAX ERP Backup — Google Drive upload failed | {datetime.now():%d %b %H:%M}"
    elif corruption:
        level, title = "critical", "Possible DATABASE CORRUPTION"
        subject = f"🔴 PRAX ERP Backup — URGENT: possible database corruption | {datetime.now():%d %b %H:%M}"
    else:
        level, title = "critical", "Backup FAILED"
        subject = f"🔴 PRAX ERP Backup — FAILED | {datetime.now():%d %b %H:%M}"

    rows = (E.row("Backup", result.get("backup_id") or "(not created)", mono=True)
            + E.row("Started", _when(result.get("started_at")))
            + E.row("Trigger", result.get("trigger"))
            + E.row("Status", result["status"], E.WARN if result["status"] == "PARTIAL" else E.BAD))
    inner = E.banner(level, title, f"{E.now_text()} IST · environment {settings.env_name}")
    inner += E.section("📋 Details", rows, first=True)
    inner += E.section("⚡ Problem", E.log_block((result.get("error") or "").splitlines()), box_style=E.LOG_BOX)
    if result.get("warnings"):
        inner += E.section("⚠️ Warnings", "".join(E.line(w, E.WARN) for w in result["warnings"]))
    steps = ["The tool retries automatically (every 30 minutes while it keeps failing).",
             "Old backups are NOT deleted while runs fail.",
             "Details and the run log: Ops Console → Backups."]
    if result["status"] == "PARTIAL":
        steps.insert(0, "Your data IS backed up on the server's backup disk; only the Google Drive copy is missing. "
                        "It is uploaded automatically once Google Drive is reachable again.")
    if corruption:
        steps.insert(0, "Do NOT restart or repair the database before talking to IT — the last good backups are kept.")
    inner += E.section("🔧 What happens next", "".join(E.line(s, icon="•") for s in steps))

    text = (f"{title}\nBackup: {result.get('backup_id')}\nStarted: {result.get('started_at')}\n"
            f"Status: {result['status']}\n\nProblem:\n{result.get('error')}\n\n"
            + "".join(f"- {s}\n" for s in steps))
    return subject, E.page(inner, TITLE), text


# ── no backup for too long ──────────────────────────────────────────────────

def overdue(settings, state, now):
    last = state.get("last_success_at")
    hours = settings.max_gap_hours
    subject = f"🔴 PRAX ERP Backup — no successful backup in {hours:g} hours | {now:%d %b %H:%M}"
    rows = (E.row("Last successful backup", _when(last), E.BAD)
            + E.row("Last backup id", state.get("last_success_id") or "never", mono=True)
            + E.row("Last error", (state.get("last_error") or "—")[:400], E.BAD))
    inner = E.banner("critical", f"No backup for over {hours:g} hours", f"{E.now_text()} IST")
    inner += E.section("📋 Details", rows, first=True)
    inner += E.section("🔧 What to do", E.line("Data entered since the last backup is NOT protected.", E.BAD, "•")
                       + E.line("Check the server is on and online, then open Ops Console → Backups.", icon="•"))
    text = f"No successful backup in {hours:g} hours.\nLast success: {last}\nLast error: {state.get('last_error')}\n"
    return subject, E.page(inner, TITLE), text


# ── daily report ────────────────────────────────────────────────────────────

def daily(settings, state, now, local_sets_count, remote_count=None, drive_about=None, remote_error=None):
    cutoff = now - timedelta(hours=24)
    recent = [h for h in state.get("history", [])
              if h.get("started_at") and datetime.fromisoformat(h["started_at"]) >= cutoff]
    failed = [h for h in recent if h["status"] == "FAILED"]
    partial = [h for h in recent if h["status"] == "PARTIAL"]
    last = state.get("last_success_at")
    age_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600 if last else None

    if age_h is None or age_h > settings.max_gap_hours or failed and not any(h["status"] == "SUCCESS" for h in recent):
        level, title = "critical", "Backups need attention"
    elif failed or partial or remote_error:
        level, title = "warning", "Backups running, with problems"
    else:
        level, title = "ok", "All backups healthy"
    subject = f"{'✅' if level == 'ok' else '⚠️' if level == 'warning' else '🔴'} PRAX ERP Daily Backup Report — {now:%d %b %Y}"

    summary = (E.row("Last successful backup", f"{_when(last)}" + (f"  ({age_h:.1f} h ago)" if age_h is not None else ""),
                     E.GOOD if age_h is not None and age_h <= settings.max_gap_hours else E.BAD)
               + E.row("Runs in last 24 h", f"{len(recent)}  ({len(recent) - len(failed) - len(partial)} ok, "
                                            f"{len(partial)} local only, {len(failed)} failed)",
                       E.BAD if failed else E.TEXT)
               + E.row("Backups on server disk", local_sets_count)
               + E.row("Backups on Google Drive", remote_count if remote_count is not None else (remote_error or "—"),
                       E.BAD if remote_error else E.TEXT))
    v = state.get("last_verify")
    if v:
        kind = E.GOOD if v.get("status") == "PASSED" else E.BAD
        summary += E.row("Last restore test", f"{v.get('status')} — {_when(v.get('at'))}", kind)
    else:
        summary += E.row("Last restore test", "not run yet", E.WARN)

    rows = []
    for h in reversed(recent):
        kind = {"SUCCESS": "ok", "PARTIAL": "warn", "FAILED": "bad"}.get(h["status"], "info")
        rows.append([E.esc(_when(h["started_at"])[-5:]), E.badge(h["status"], kind), E.esc(h.get("trigger")),
                     E.esc(human_bytes(h.get("db_bytes"))), E.esc(human_bytes(h.get("media_bytes"))),
                     "✅" if h.get("uploaded") else "—"])
    runs = E.table(["Time", "Status", "Trigger", "DB", "Files", "Drive"], rows) if rows else E.line("No runs in the last 24 hours", E.BAD)

    usage = shutil.disk_usage(settings.local_dir)
    storage = E.bar(f"Backup disk ({settings.local_dir})", 100 * usage.used / usage.total,
                    f"{human_bytes(usage.free)} free of {human_bytes(usage.total)}")
    if drive_about and drive_about.get("total"):
        storage += E.bar("Google Drive", 100 * drive_about.get("used", 0) / drive_about["total"],
                         f"{human_bytes(drive_about.get('used'))} used of {human_bytes(drive_about['total'])}")

    issues = ""
    for h in recent:
        if h.get("error"):
            issues += E.line(f"{_when(h['started_at'])}: {h['error'][:300]}", E.BAD, "•")
        for w in h.get("warnings") or []:
            issues += E.line(f"{_when(h['started_at'])}: {w}", E.WARN, "•")

    inner = E.banner(level, title, f"{now:%d %b %Y} · environment {settings.env_name}")
    inner += E.section("📊 Summary", summary, first=True)
    inner += E.section("🕐 Runs in the last 24 hours", runs)
    inner += E.section("💾 Storage", storage)
    if issues:
        inner += E.section("⚠️ Problems & warnings", issues)

    text = (f"{title}\nLast successful backup: {last}\nRuns in 24 h: {len(recent)} "
            f"({len(failed)} failed, {len(partial)} local only)\nOn server disk: {local_sets_count}\n"
            f"On Google Drive: {remote_count}\n")
    return subject, E.page(inner, TITLE), text


# ── weekly restore test ─────────────────────────────────────────────────────

def restore_test(report):
    status = report["status"]
    level = {"PASSED": "ok", "PROBLEMS": "warning"}.get(status, "critical")
    title = {"PASSED": "Restore test PASSED", "PROBLEMS": "Restore test found problems"}.get(status, "Restore test FAILED")
    icon = {"ok": "✅", "warning": "⚠️"}.get(level, "🔴")
    subject = f"{icon} PRAX ERP Backup — {title} | {datetime.now():%d %b %H:%M}"
    rows = (E.row("Backup tested", report.get("backup_id") or "—", mono=True)
            + E.row("Copy used", report.get("source", "—"))
            + E.row("Started", _when(report.get("at")))
            + E.row("Finished", _when(report.get("finished_at")))
            + E.row("Result", status, E.GOOD if status == "PASSED" else E.BAD))
    inner = E.banner(level, title, f"{E.now_text()} IST")
    inner += E.section("📋 Details", rows, first=True)
    inner += E.section("🔍 What was checked", "".join(E.line(n, icon="✔") for n in report.get("notes", [])) or E.line("—"))
    if report.get("problems"):
        inner += E.section("⚡ Problems", "".join(E.line(p, E.BAD, "•") for p in report["problems"][:50]))
    text = (f"{title}\nBackup: {report.get('backup_id')}\nResult: {status}\n\n"
            + "".join(f"- {n}\n" for n in report.get("notes", []))
            + ("\nProblems:\n" + "".join(f"! {p}\n" for p in report["problems"]) if report.get("problems") else ""))
    return subject, E.page(inner, TITLE), text


# ── test ────────────────────────────────────────────────────────────────────

def test_message(settings, category):
    subject = "ℹ️ PRAX ERP — test email"
    inner = E.banner("info", "Test email", f"{E.now_text()} IST")
    inner += E.section("📋 Details", E.row("Alert type", category) + E.row("Environment", settings.env_name), first=True)
    inner += E.section("✔ Result", E.line("If you can read this, alerts of this type reach you.", E.GOOD))
    return subject, E.page(inner, TITLE), f"Test email for alert type {category}.\n"


# ── console actions ─────────────────────────────────────────────────────────

def console_action(action, user, details):
    subject = f"ℹ️ PRAX ERP Ops Console — {action} | {datetime.now():%d %b %H:%M}"
    rows = E.row("Action", action) + E.row("By", user) + "".join(E.row(k, v) for k, v in details.items())
    inner = E.banner("info", action, f"{E.now_text()} IST")
    inner += E.section("📋 Details", rows, first=True)
    text = f"{action} by {user}\n" + "".join(f"{k}: {v}\n" for k, v in details.items())
    return subject, E.page(inner, "PRAX ERP Ops Console"), text
