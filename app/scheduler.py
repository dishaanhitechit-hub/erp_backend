"""
Monthly report scheduler.
Fires once a month (configurable via ENV) and sends one email per module.
Start it by calling init_scheduler(app) inside create_app().
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)


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


def init_scheduler(app):
    day  = app.config.get("MAIL_SCHEDULE_DAY",  1)
    hour = app.config.get("MAIL_SCHEDULE_HOUR", 8)
    tz   = app.config.get("MAIL_TIMEZONE", "Asia/Kolkata")

    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        func=_run_all_summaries,
        args=[app],
        trigger=CronTrigger(day=day, hour=hour, minute=0, timezone=tz),
        id="monthly_report",
        name="Monthly ERP Email Reports",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Monthly report scheduler started — fires on day=%s at %s:00 (%s)", day, hour, tz
    )
    return scheduler
