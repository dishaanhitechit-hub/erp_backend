"""
Project Management module — monthly email summary.
Covers: Budget, Drawing Register, BBS Register, Hindrance Register,
        Concrete Registry, Custom Billing (BillingMaster).
All grouped by project.
"""
from datetime import datetime
from collections import defaultdict, Counter

from app.extensions import db
from app.models.project import Project
from app.models.budget import BudgetMaster
from app.models.drawingRegister import DrawingRegister
from app.models.bbsRegister import BbsRegister
from app.models.hindranceRegister import HindranceRegister
from app.models.concrete_registry import ConcreteRegistry
from app.models.billingMaster import BillingMaster

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


def _group(rows):
    g = defaultdict(list)
    for r in rows:
        g[r.project_code].append(r)
    return g


# ── section renderers ─────────────────────────────────────────────────────────

def _render_budget(rows, proj_map):
    html = section_header("Budget")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    total_count, total_amount, total_tec, total_profit = 0, 0.0, 0.0, 0.0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = []
        for r in items:
            amount = float(r.total_initial_cost or 0)
            drcw   = float(r.total_cc_cost      or 0)
            od     = r.overhead_data or {}
            overhead = sum(
                float(e.get("estimatedCost") or 0)
                for e in od.get("projectOverhead", []) + od.get("employeeOverhead", [])
            )
            tec    = drcw + overhead
            profit = amount - tec
            profit_pct = round(profit / amount * 100, 2) if amount else 0.0
            trows.append([
                r.budget_no, r.workflow_status,
                amount, drcw, overhead, tec, profit, f"{profit_pct}%",
            ])
            total_count  += 1
            total_amount += amount
            total_tec    += tec
            total_profit += profit
        html += table(
            ["Budget No", "Status", "Sale Order Amt", "Direct Expenses", "Overhead", "TEC", "Profit", "Profit %"],
            trows,
            amount_cols={2, 3, 4, 5, 6},
        )
    html = stat_row([
        ("Budgets Created", str(total_count)),
        ("Total Amount",    f"₹{total_amount:,.2f}"),
        ("Total TEC",       f"₹{total_tec:,.2f}"),
        ("Total Profit",    f"₹{total_profit:,.2f}"),
    ]) + html
    return html


def _render_drawings(rows, proj_map):
    html = section_header("Drawing Register")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [r.drawing_no or "—", r.drawing_title or "—", r.workflow_status]
            for r in items
        ]
        html += table(["Drawing No", "Title", "Status"], trows)
    return html


def _render_bbs(rows, proj_map):
    html = section_header("BBS Register")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [[r.bbs_no or "—", r.workflow_status] for r in items]
        html += table(["BBS No", "Status"], trows)
    return html


def _render_hindrance(rows, proj_map):
    html = section_header("Hindrance Register")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [[r.hindrance_no or "—", r.workflow_status] for r in items]
        html += table(["Hindrance No", "Status"], trows)
    return html


def _render_concrete(rows, proj_map):
    html = section_header("Concrete Registry")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = [
            [
                str(r.id),
                str(r.created_at.date()) if r.created_at else "—",
            ]
            for r in items
        ]
        html += table(["Record ID", "Date"], trows)
    return html


def _render_billing(rows, proj_map):
    html = section_header("Custom Billing")
    if not rows:
        return html + no_data_note()
    groups = _group(rows)
    total_count, total_amt = 0, 0
    for code, items in sorted(groups.items()):
        name, client = proj_map.get(code, (code, ""))
        html += project_block_open(code, name, client)
        trows = []
        for r in items:
            trows.append([r.billing_no or "—", r.title or "—", r.workflow_status, r.pre_certified_amount])
            total_count += 1
            total_amt += float(r.pre_certified_amount or 0)
        html += table(["Billing No", "Title", "Status", "Pre-Certified Amount"], trows, amount_cols={3})
    html = stat_row([("Bills Raised", str(total_count)), ("Total Amount", f"₹{total_amt:,.2f}")]) + html
    return html


# ── main ──────────────────────────────────────────────────────────────────────

def build_and_send():
    start, end = last_month_range()
    proj_map   = _project_map()

    budgets    = _q(BudgetMaster,     start, end)
    drawings   = _q(DrawingRegister,  start, end)
    bbs        = _q(BbsRegister,      start, end)
    hindrances = _q(HindranceRegister, start, end)
    concrete   = _q(ConcreteRegistry, start, end)
    billings   = _q(BillingMaster,    start, end)

    overview = stat_row([
        ("Budgets",       str(len(budgets))),
        ("Drawings",      str(len(drawings))),
        ("BBS Entries",   str(len(bbs))),
        ("Hindrances",    str(len(hindrances))),
    ])

    body = (
        overview
        + _render_budget(budgets,     proj_map)
        + _render_drawings(drawings,  proj_map)
        + _render_bbs(bbs,            proj_map)
        + _render_hindrance(hindrances, proj_map)
        + _render_concrete(concrete,  proj_map)
        + _render_billing(billings,   proj_map)
    )

    pl      = period_label(start, end)
    html    = build_email("Project Management Module", pl, datetime.now(), body)
    subject = f"[ERP] Project Mgmt — Monthly Summary ({month_label(start)})"

    send_monthly_report(
        subject,
        html,
        current_app.config.get("MAIL_RECIPIENT_PROJECT_MGMT", ""),
    )
