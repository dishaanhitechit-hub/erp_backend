"""
Project module — monthly email summary.
Covers: new projects created + all active projects overview.
"""
from datetime import datetime
from collections import Counter

from app.extensions import db
from app.models.project import Project

from app.utils.email_template import (
    stat_row, section_header, table, no_data_note, build_email
)
from app.utils.date_utils import month_label, period_label, last_month_range
from app.utils.email_service import send_monthly_report
from flask import current_app


def build_and_send():
    start, end = last_month_range()

    new_projects = db.session.query(Project).filter(
        Project.created_at >= start, Project.created_at <= end
    ).all()

    all_projects = db.session.query(Project).all()
    status_counts = Counter(p.status for p in all_projects)

    overview = stat_row([
        ("New This Month",  str(len(new_projects))),
        ("Total Projects",  str(len(all_projects))),
        ("Active",          str(status_counts.get("Active", 0))),
        ("Completed",       str(status_counts.get("Completed", 0))),
    ])

    html_body = overview

    # New projects table
    html_body += section_header("New Projects This Month")
    if new_projects:
        trows = [
            [
                p.project_code,
                p.project_name or "—",
                p.client_name or "—",
                str(p.created_at.date()) if p.created_at else "—",
                p.status or "—",
            ]
            for p in new_projects
        ]
        html_body += table(
            ["Code", "Project Name", "Client", "Created Date", "Status"], trows
        )
    else:
        html_body += no_data_note("No new projects were created this month.")

    # All-projects status breakdown
    html_body += section_header("All Projects — Status Breakdown")
    status_rows = [[status, str(count)] for status, count in sorted(status_counts.items())]
    html_body += table(["Status", "Count"], status_rows)

    pl      = period_label(start, end)
    html    = build_email("Project Module", pl, datetime.now(), html_body)
    subject = f"[ERP] Project Module — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_PROJECT", ""),
    )
