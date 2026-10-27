"""
HR module — monthly email summary.
HR is not project-scoped, so this is a flat summary.
"""
from datetime import datetime
from collections import Counter

from app.extensions import db
from app.models.employee import Employee
from app.models.recruitment import JobOpening, Candidate
from app.models.payrollModel import PayrollRun, PayrollEntry
from app.models.performanceModel import PerformanceReview
from app.models.onboarding import OnboardingTask

from app.utils.email_template import (
    stat_row, section_header, table, no_data_note, build_email
)
from app.utils.date_utils import month_label, period_label, last_month_range
from app.utils.email_service import send_monthly_report
from flask import current_app


def _q(model, start, end):
    return db.session.query(model).filter(
        model.created_at >= start, model.created_at <= end
    ).all()


def _render_employees(rows):
    html = section_header("New Employees")
    if not rows:
        return html + no_data_note()
    trows = [
        [r.emp_code, r.username or "—", r.designation or "—", r.department or "—", r.employee_status]
        for r in rows
    ]
    return html + table(["Emp Code", "Name", "Designation", "Department", "Status"], trows)


def _render_recruitment(jobs, candidates):
    html = section_header("Recruitment")
    if not jobs and not candidates:
        return html + no_data_note()

    html += stat_row([
        ("Job Openings",  str(len(jobs))),
        ("Candidates",    str(len(candidates))),
        ("Hired",         str(sum(1 for c in candidates if c.stage == "Joined"))),
        ("Rejected",      str(sum(1 for c in candidates if c.stage == "Rejected"))),
    ])

    if jobs:
        html += "<p style='font-weight:600;font-size:12px;margin:12px 0 6px;'>Job Openings</p>"
        trows = [[j.title or "—", j.department or "—", j.status, str(len(j.candidates))] for j in jobs]
        html += table(["Title", "Department", "Status", "Applicants"], trows)

    if candidates:
        html += "<p style='font-weight:600;font-size:12px;margin:12px 0 6px;'>Candidates</p>"
        trows = [[c.name or "—", c.email or "—", c.stage or "—"] for c in candidates]
        html += table(["Name", "Email", "Stage"], trows)

    return html


def _render_payroll(runs, entries):
    html = section_header("Payroll")
    if not runs:
        return html + no_data_note()

    total_salary = sum(float(e.net_pay or 0) for e in entries)
    html += stat_row([
        ("Payroll Runs",   str(len(runs))),
        ("Employees Paid", str(len(entries))),
        ("Total Net Pay",  f"₹{total_salary:,.2f}"),
    ])

    trows = [[r.month or "—", r.year or "—", r.status] for r in runs]
    html += table(["Month", "Year", "Status"], trows)
    return html


def _render_performance(reviews):
    html = section_header("Performance Reviews")
    if not reviews:
        return html + no_data_note()

    rating_buckets = Counter()
    for r in reviews:
        if r.rating is None:
            rating_buckets["Unrated"] += 1
        elif float(r.rating) >= 4.0:
            rating_buckets["Excellent (4–5)"] += 1
        elif float(r.rating) >= 3.0:
            rating_buckets["Good (3–4)"] += 1
        elif float(r.rating) >= 2.0:
            rating_buckets["Average (2–3)"] += 1
        else:
            rating_buckets["Below Average (<2)"] += 1

    html += stat_row([("Reviews Submitted", str(len(reviews)))])

    bucket_rows = [[cat, str(count)] for cat, count in rating_buckets.items()]
    html += table(["Rating Band", "Count"], bucket_rows)
    return html


def _render_onboarding(tasks):
    html = section_header("Onboarding Tasks")
    if not tasks:
        return html + no_data_note()
    completed = sum(1 for t in tasks if getattr(t, "status", "") == "Completed")
    html += stat_row([
        ("Total Tasks",  str(len(tasks))),
        ("Completed",    str(completed)),
        ("Pending",      str(len(tasks) - completed)),
    ])
    return html


def build_and_send():
    start, end = last_month_range()

    new_employees  = _q(Employee,           start, end)
    new_jobs       = _q(JobOpening,         start, end)
    new_candidates = _q(Candidate,          start, end)
    payroll_runs   = _q(PayrollRun,         start, end)
    payroll_entries= _q(PayrollEntry,       start, end)
    perf_reviews   = _q(PerformanceReview,  start, end)
    onboarding     = _q(OnboardingTask,     start, end)

    overview = stat_row([
        ("New Employees",   str(len(new_employees))),
        ("Job Openings",    str(len(new_jobs))),
        ("New Candidates",  str(len(new_candidates))),
        ("Payroll Runs",    str(len(payroll_runs))),
    ])

    body = (
        overview
        + _render_employees(new_employees)
        + _render_recruitment(new_jobs, new_candidates)
        + _render_payroll(payroll_runs, payroll_entries)
        + _render_performance(perf_reviews)
        + _render_onboarding(onboarding)
    )

    pl      = period_label(start, end)
    html    = build_email("HR Module", pl, datetime.now(), body)
    subject = f"[ERP] HR Module — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_HR", ""),
    )
