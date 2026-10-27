"""
Resources module — monthly email summary.
Covers: Indent, GRN, GIN, SRN, Machinery Log, Manpower.
Grouped by project where project_code exists.
"""
from datetime import datetime
from collections import defaultdict

from app.extensions import db
from app.models.project import Project
from app.models.indent_master import IndentMaster
from app.models.grnMaster import GrnMaster
from app.models.ginMaster import GinMaster
from app.models.srnMaster import SrnMaster
from app.models.machineryLogBook import MachineryLogBook
from app.models.manpower import ManpowerWorker

from app.utils.email_template import (
    stat_row, section_header, project_block_open, table, no_data_note, build_email
)
from app.utils.date_utils import month_label, period_label, last_month_range
from app.utils.email_service import send_monthly_report
from flask import current_app


def _project_map():
    rows = db.session.query(Project.project_code, Project.project_name, Project.client_name).all()
    return {r.project_code: (r.project_name or "", r.client_name or "") for r in rows}


def _q(model, start, end):
    return db.session.query(model).filter(
        model.created_at >= start, model.created_at <= end
    ).all()


def _group(rows, code_attr="project_code"):
    g = defaultdict(list)
    for r in rows:
        g[getattr(r, code_attr, "UNKNOWN")].append(r)
    return g


def _render_project_section(rows, proj_map, heading, col_attr, col_label):
    html = section_header(heading)
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [getattr(r, col_attr) or "—", r.workflow_status]
            for r in items
        ]
        html += table([col_label, "Status"], trows)
    return html


def _render_indents(rows, proj_map):
    html = section_header("Indents")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [r.indent_no or "—", r.workflow_status, r.order_status or "—"]
            for r in items
        ]
        html += table(["Indent No", "Workflow Status", "Order Status"], trows)
    return html


def _render_machinery(rows, proj_map):
    html = section_header("Machinery Log Book")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [
                str(r.log_date) if r.log_date else "—",
                str(r.id),
            ]
            for r in items
        ]
        html += table(["Log Date", "Record ID"], trows)
    return html


def _render_manpower(rows):
    html = section_header("Manpower")
    if not rows:
        return html + no_data_note()
    html += stat_row([("Workers Logged", str(len(rows)))])
    trows = [
        [r.worker_name or "—", r.trade or "—", str(r.created_at.date()) if r.created_at else "—"]
        for r in rows
    ]
    html += table(["Worker Name", "Trade", "Date"], trows)
    return html


def build_and_send():
    start, end = last_month_range()
    proj_map   = _project_map()

    indents   = _q(IndentMaster,     start, end)
    grns      = _q(GrnMaster,        start, end)
    gins      = _q(GinMaster,        start, end)
    srns      = _q(SrnMaster,        start, end)
    machinery = _q(MachineryLogBook, start, end)
    manpower  = _q(ManpowerWorker,   start, end)

    overview = stat_row([
        ("Indents",    str(len(indents))),
        ("GRN",        str(len(grns))),
        ("GIN",        str(len(gins))),
        ("SRN",        str(len(srns))),
    ])

    body = (
        overview
        + _render_indents(indents,       proj_map)
        + _render_project_section(grns,  proj_map, "Goods Receipt Notes (GRN)", "grn_no", "GRN No")
        + _render_project_section(gins,  proj_map, "Goods Issue Notes (GIN)",   "gin_no", "GIN No")
        + _render_project_section(srns,  proj_map, "Site Return Notes (SRN)",   "srn_no", "SRN No")
        + _render_machinery(machinery,   proj_map)
        + _render_manpower(manpower)
    )

    pl      = period_label(start, end)
    html    = build_email("Resources Module", pl, datetime.now(), body)
    subject = f"[ERP] Resources Module — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_RESOURCES", ""),
    )
