"""
Scheduled jobs: monthly e-mail reports, Daily Progress Report jobs, cleanup.

Where the jobs run — environment variable SCHEDULER_MODE:
    embedded (default)  every Gunicorn worker starts a scheduler, as before.
                        Each job still runs only ONCE (see "run once" below),
                        so this is safe with any number of workers.
    off                 no scheduler in this process. Use this for the web
                        workers when the separate scheduler process runs:
                            python scheduler_main.py

Run once, whatever the number of workers / processes (shared table
`runtime_store`, app/utils/runtime_store.py):
    * monthly report  — one run per calendar month;
    * DPR evening job — one run per day;
    * DPR photo sweep and cleanup — one run at a time (a lease that expires
      if the process running it dies).

This replaces the Postgres session-level advisory lock used before, which
does not work through PgBouncer in transaction mode, and fixes the monthly
report, which had no lock at all and was sent once per worker.
"""
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_started_lock = threading.Lock()
_started = None  # the scheduler running in this process, if any


def _scheduler_mode():
    return (os.getenv("SCHEDULER_MODE") or "embedded").strip().lower()


def _owner():
    return f"pid-{os.getpid()}"


def _run_all_summaries(app):
    """Run inside an app-context so db / current_app work."""
    with app.app_context():
        from app.modules.finance.monthly_summary      import build_and_send as finance_send
        from app.modules.hr.monthly_summary           import build_and_send as hr_send
        from app.modules.billing.monthly_summary      import build_and_send as billing_send
        from app.modules.project.monthly_summary      import build_and_send as project_send
        from app.modules.project_mgmt.monthly_summary import build_and_send as pm_send
        from app.modules.resources.monthly_summary    import build_and_send as resources_send

        jobs = [
            ("Finance",          finance_send),
            ("HR",               hr_send),
            ("Billing",          billing_send),
            ("Project",          project_send),
            ("Project Mgmt",     pm_send),
            ("Resources",        resources_send),
        ]

        for name, fn in jobs:
            try:
                fn()
                logger.info("Monthly summary sent: %s", name)
            except Exception as exc:
                logger.exception("Failed to send monthly summary for %s: %s", name, exc)
                # Roll back any aborted transaction so the next module starts clean.
                try:
                    from app.extensions import db
                    db.session.rollback()
                except Exception:
                    pass


def _run_once_per_period(app, job_name, period_key, fn, keep_seconds):
    """
    Run `fn(app)` once for this period (e.g. "2026-11" or "2026-11-14"), in
    whichever process gets there first. The marker is kept, not released.
    """
    from app.utils import runtime_store

    with app.app_context():
        if not runtime_store.claim(f"once:{job_name}:{period_key}", keep_seconds, owner=_owner()):
            logger.info("Job %s for %s already ran in another process — skipped", job_name, period_key)
            return
    logger.info("Job %s for %s started", job_name, period_key)
    fn(app)


def _monthly_report(app, tz):
    month = datetime.now(ZoneInfo(tz)).strftime("%Y-%m")
    _run_once_per_period(app, "monthly_report", month, _run_all_summaries, keep_seconds=40 * 86400)


def _single_run(app, job_name, fn, lease_seconds):
    """
    Run `fn` in only one process at a time. The lease expires after
    `lease_seconds`, so a process that died while running does not block the
    job forever.
    """
    with app.app_context():
        from app.extensions import db
        from app.utils import runtime_store

        key = f"job:{job_name}"
        if not runtime_store.claim(key, lease_seconds, owner=_owner()):
            return
        try:
            fn()
        except Exception:
            logger.exception("Scheduled job %s failed", job_name)
            db.session.rollback()
        finally:
            runtime_store.release(key)
            db.session.remove()


def _dpr_auto_generate_once(app, tz):
    """The evening DPR draft job: once per day."""
    from app.modules.project_mgmt.site_report import service as dpr

    def run(app_):
        _single_run(app_, "dpr_auto_generate", dpr.auto_generate_today, lease_seconds=2 * 3600)

    day = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    _run_once_per_period(app, "dpr_auto_generate", day, run, keep_seconds=3 * 86400)


def _add_dpr_jobs(scheduler, app, tz):
    """Daily Progress Report: retry photos waiting for AI; write drafts every evening."""
    from app.modules.project_mgmt.site_report import service as dpr

    scheduler.add_job(
        func=_single_run, args=[app, "dpr_photo_sweep", dpr.sweep_pending, 30 * 60],
        trigger="interval", minutes=5, id="dpr_photo_sweep", replace_existing=True,
        max_instances=1, coalesce=True,
    )
    hour = int(os.getenv("DPR_AUTO_HOUR") or 19)
    scheduler.add_job(
        func=_dpr_auto_generate_once, args=[app, tz],
        trigger=CronTrigger(hour=hour, minute=0, timezone=tz), id="dpr_auto_generate",
        replace_existing=True, max_instances=1, coalesce=True,
    )


def _purge_runtime_store():
    from app.utils import runtime_store
    deleted = runtime_store.purge_expired()
    if deleted:
        logger.info("runtime_store: %s expired rows deleted", deleted)


def init_scheduler(app, force=False):
    """
    Start the scheduler for this process. Does nothing when
    SCHEDULER_MODE=off (unless `force`, used by scheduler_main.py) or when a
    scheduler is already running in this process.
    """
    global _started
    if not force and _scheduler_mode() == "off":
        logger.info("Scheduler not started in this process (SCHEDULER_MODE=off)")
        return None

    with _started_lock:
        if _started is not None:
            return _started

        day  = app.config.get("MAIL_SCHEDULE_DAY",  1)
        hour = app.config.get("MAIL_SCHEDULE_HOUR", 8)
        tz   = app.config.get("MAIL_TIMEZONE", "Asia/Kolkata")

        scheduler = BackgroundScheduler(timezone=tz)
        scheduler.add_job(
            func=_monthly_report,
            args=[app, tz],
            trigger=CronTrigger(day=day, hour=hour, minute=0, timezone=tz),
            id="monthly_report",
            name="Monthly ERP Email Reports",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _add_dpr_jobs(scheduler, app, tz)
        scheduler.add_job(
            func=_single_run, args=[app, "runtime_store_purge", _purge_runtime_store, 15 * 60],
            trigger="interval", hours=1, id="runtime_store_purge", replace_existing=True,
            max_instances=1, coalesce=True,
        )
        scheduler.start()
        _started = scheduler
        logger.info(
            "Scheduler started (pid %s) — monthly report on day=%s at %s:00 (%s)",
            os.getpid(), day, hour, tz,
        )
        return scheduler
