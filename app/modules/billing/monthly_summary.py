"""
Billing module — monthly email summary.
Covers: BRR (Bill Receive Register), BRB (BRR Billing), BRG (BRR Billing GRN), BRS (BRR Billing SRN).
All grouped by project.
"""
from datetime import datetime
from collections import defaultdict

from app.extensions import db
from app.models.project import Project
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster
from app.models.brgMaster import BrgMaster
from app.models.brsMaster import BrsMaster

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


def _render_brr(rows, proj_map):
    html = section_header("Bill Receive Register (BRR)")
    if not rows:
        return html + no_data_note()
    groups = defaultdict(list)
    for r in rows:
        groups[r.project_code].append(r)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = []
        for r in items:
            trows.append([r.brr_no or "—", r.workflow_status, r.total_amount])
            total_count += 1
            total_amt += float(r.total_amount or 0)
        html += table(["BRR No", "Status", "Total Amount"], trows, amount_cols={2})
    html = stat_row([("Total BRR", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_brb(rows, proj_map):
    html = section_header("BRR Billing (BRB)")
    if not rows:
        return html + no_data_note()
    groups = defaultdict(list)
    for r in rows:
        groups[r.project_code].append(r)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = []
        for r in items:
            trows.append([r.brb_no or "—", r.workflow_status, r.total_amount])
            total_count += 1
            total_amt += float(r.total_amount or 0)
        html += table(["BRB No", "Status", "Total Amount"], trows, amount_cols={2})
    html = stat_row([("Total BRB", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


def _render_generic(rows, proj_map, heading, no_attr):
    html = section_header(heading)
    if not rows:
        return html + no_data_note()
    groups = defaultdict(list)
    for r in rows:
        groups[r.project_code].append(r)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [getattr(r, no_attr) or "—", r.workflow_status, r.total_amount]
            for r in items
        ]
        html += table(["Reference No", "Status", "Amount"], trows, amount_cols={2})
    return html


def build_and_send():
    start, end = last_month_range()
    proj_map   = _project_map()

    brr = _q(BrrMaster, start, end)
    brb = _q(BrbMaster, start, end)
    brg = _q(BrgMaster, start, end)
    brs = _q(BrsMaster, start, end)

    overview = stat_row([
        ("BRR Entries",   str(len(brr))),
        ("BRB Billings",  str(len(brb))),
        ("BRG (GRN)",     str(len(brg))),
        ("BRS (SRN)",     str(len(brs))),
    ])

    body = (
        overview
        + _render_brr(brr, proj_map)
        + _render_brb(brb, proj_map)
        + _render_generic(brg, proj_map, "BRR Billing GRN (BRG)", "brg_no")
        + _render_generic(brs, proj_map, "BRR Billing SRN (BRS)", "brs_no")
    )

    pl      = period_label(start, end)
    html    = build_email("Billing Module", pl, datetime.now(), body)
    subject = f"[ERP] Billing Module — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_BILLING", ""),
    )
