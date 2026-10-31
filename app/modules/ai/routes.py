from flask import request, jsonify
from flask_jwt_extended import jwt_required
from . import ai_bp
from .client import ask_claude
from app.extensions import db
from sqlalchemy import text


# ── Sale Bill Suggestions ────────────────────────────────────────────────────

@ai_bp.route("/suggest/sale-bill", methods=["POST"])
@jwt_required()
def suggest_sale_bill():
    """
    Body: { "project_code": "...", "query": "suggest items for this bill" }
    Fetches last 10 sale bills for the project and asks Claude for suggestions.
    """
    data = request.get_json(silent=True) or {}
    project_code = data.get("project_code", "")
    user_query = data.get("query", "Suggest items and amounts for the next sale bill.")

    if not project_code:
        return jsonify({"error": "project_code is required"}), 400

    rows = db.session.execute(
        text("""
            SELECT
                sbm.sale_bill_no,
                sbm.invoice_date,
                sbm.total_invoice_amount,
                sbm.workflow_status,
                sbi.cc_code,
                sbi.cc_name,
                sbi.description,
                sbi.basic_amount,
                sbm.erp_no
            FROM sale_bill_master sbm
            JOIN sale_bill_items sbi ON sbi.sale_bill_id = sbm.id
            WHERE sbm.project_code = :pc
              AND sbm.status = 'Active'
            ORDER BY sbm.invoice_date DESC
            LIMIT 60
        """),
        {"pc": project_code},
    ).fetchall()

    if not rows:
        return jsonify({"suggestion": "No previous sale bills found for this project. Cannot generate suggestions yet."}), 200

    history = [
        {
            "bill_no": r[0],
            "date": str(r[1]),
            "total": float(r[2] or 0),
            "status": r[3],
            "cc_code": r[4],
            "cc_name": r[5],
            "description": r[6],
            "basic_amount": float(r[7] or 0),
            "erp_no": r[8] or "",
        }
        for r in rows
    ]

    system_prompt = (
        "You are an ERP assistant for a construction/engineering company. "
        "You help billing teams prepare sale bills by analyzing past billing history. "
        "Be concise, practical, and use bullet points. Amounts in INR."
    )

    user_message = (
        f"Project: {project_code}\n\n"
        f"Past sale bill history (last 10 bills, all items):\n{history}\n\n"
        f"Question: {user_query}"
    )

    suggestion = ask_claude(system_prompt, user_message)

    # Derive auto-fill fields from billing history
    from collections import Counter
    cc_counts = Counter(r["cc_code"] for r in history if r["cc_code"])
    top_cc = cc_counts.most_common(1)[0][0] if cc_counts else None
    if top_cc:
        same_cc = [r for r in history if r["cc_code"] == top_cc]
        recent_amounts = [r["basic_amount"] for r in same_cc[:10]]
        avg_amount = sum(recent_amounts) / len(recent_amounts)
        top_cc_name = same_cc[0]["cc_name"] or top_cc
    else:
        avg_amount = 0
        top_cc_name = ""

    # Most recently used sale order number
    order_counts = Counter(r["erp_no"] for r in history if r["erp_no"])
    top_order = order_counts.most_common(1)[0][0] if order_counts else ""

    fields = {
        "erp_no": top_order,
        "cc_code": top_cc or "",
        "cc_name": top_cc_name,
        "basic_amount": round(avg_amount, 2),
        "gst_type": "IGST",
    }

    return jsonify({"suggestion": suggestion, "fields": fields}), 200


# ── General Business Chat ─────────────────────────────────────────────────────

@ai_bp.route("/chat", methods=["POST"])
@jwt_required()
def business_chat():
    """
    Body: { "query": "What is my total sale this month?", "module": "finance" }
    Fetches a summary from the relevant module and answers in plain language.
    """
    data = request.get_json(silent=True) or {}
    user_query = data.get("query", "")
    module = data.get("module", "finance")

    if not user_query:
        return jsonify({"error": "query is required"}), 400

    context = _get_module_summary(module)

    system_prompt = (
        "You are a business intelligence assistant for an ERP system. "
        "Answer questions about the company's data concisely. "
        "Use only the provided data. If data is insufficient, say so."
    )

    user_message = f"Module: {module}\nData summary:\n{context}\n\nQuestion: {user_query}"

    answer = ask_claude(system_prompt, user_message, max_tokens=512)
    return jsonify({"answer": answer}), 200


# ── Purchase Bill Suggestions ─────────────────────────────────────────────────

@ai_bp.route("/suggest/purchase-bill", methods=["POST"])
@jwt_required()
def suggest_purchase_bill():
    """
    Body: { "project_code": "...", "vendor_id": 5, "query": "optional" }
    Fetches past purchase bills for the project (optionally filtered by vendor)
    and asks Claude for item/amount suggestions.
    """
    data = request.get_json(silent=True) or {}
    project_code = data.get("project_code", "")
    vendor_id    = data.get("vendor_id")
    user_query   = data.get("query", "Suggest items and amounts for the next purchase bill.")

    if not project_code:
        return jsonify({"error": "project_code is required"}), 400

    vendor_filter = "AND pbm.vendor_id = :vid" if vendor_id else ""
    params = {"pc": project_code}
    if vendor_id:
        params["vid"] = vendor_id

    rows = db.session.execute(
        text(f"""
            SELECT
                pbm.purchase_bill_no,
                pbm.processing_date,
                pbm.total_invoice_amount,
                pbm.workflow_status,
                v.ledger_name  AS vendor_name,
                pbi.cc_code,
                pbi.cc_name,
                pbi.description,
                pbi.basic_amount
            FROM purchase_bill_master pbm
            LEFT JOIN vendors v ON v.id = pbm.vendor_id
            JOIN purchase_bill_items pbi ON pbi.purchase_bill_id = pbm.id
            WHERE pbm.project_code = :pc
              AND pbm.status = 'Active'
              {vendor_filter}
            ORDER BY pbm.processing_date DESC
            LIMIT 60
        """),
        params,
    ).fetchall()

    if not rows:
        return jsonify({"suggestion": "No previous purchase bills found. Cannot generate suggestions yet."}), 200

    # vendor summary — top vendors by spend for this project
    vendor_rows = db.session.execute(
        text("""
            SELECT v.ledger_name, COUNT(*) AS bill_count,
                   SUM(pbm.total_invoice_amount) AS total_spend
            FROM purchase_bill_master pbm
            LEFT JOIN vendors v ON v.id = pbm.vendor_id
            WHERE pbm.project_code = :pc AND pbm.status = 'Active'
            GROUP BY v.ledger_name
            ORDER BY total_spend DESC
            LIMIT 10
        """),
        {"pc": project_code},
    ).fetchall()

    history = [
        {
            "bill_no":      r[0],
            "date":         str(r[1]),
            "total":        float(r[2] or 0),
            "status":       r[3],
            "vendor":       r[4],
            "cc_code":      r[5],
            "cc_name":      r[6],
            "description":  r[7],
            "basic_amount": float(r[8] or 0),
        }
        for r in rows
    ]
    top_vendors = [
        {"vendor": r[0], "bills": r[1], "total_spend": float(r[2] or 0)}
        for r in vendor_rows
    ]

    system_prompt = (
        "You are an ERP assistant for a construction/engineering company. "
        "You help procurement teams prepare purchase bills by analyzing past billing history. "
        "Be concise, use bullet points. Amounts in INR. "
        "Highlight the most-used vendors and typical item amounts."
    )

    user_message = (
        f"Project: {project_code}\n\n"
        f"Top vendors by spend:\n{top_vendors}\n\n"
        f"Past purchase bill items (recent):\n{history}\n\n"
        f"Question: {user_query}"
    )

    suggestion = ask_claude(system_prompt, user_message)
    return jsonify({"suggestion": suggestion}), 200


# ── Finance Insights ──────────────────────────────────────────────────────────

@ai_bp.route("/insights/finance", methods=["GET"])
@jwt_required()
def finance_insights():
    """
    Returns Claude's analysis of the last 3 months of sale vs purchase data.
    Optional query param: ?project_code=XYZ to scope to one project.
    """
    project_code = request.args.get("project_code")
    pc_filter = "AND project_code = :pc" if project_code else ""
    params = {"pc": project_code} if project_code else {}

    sale_rows = db.session.execute(
        text(f"""
            SELECT DATE_TRUNC('month', invoice_date) AS month,
                   COUNT(*) AS bills,
                   SUM(total_invoice_amount) AS total
            FROM sale_bill_master
            WHERE status = 'Active'
              AND invoice_date >= NOW() - INTERVAL '3 months'
              {pc_filter}
            GROUP BY 1 ORDER BY 1 DESC
        """),
        params,
    ).fetchall()

    purchase_rows = db.session.execute(
        text(f"""
            SELECT DATE_TRUNC('month', processing_date) AS month,
                   COUNT(*) AS bills,
                   SUM(total_invoice_amount) AS total
            FROM purchase_bill_master
            WHERE status = 'Active'
              AND processing_date >= NOW() - INTERVAL '3 months'
              {pc_filter}
            GROUP BY 1 ORDER BY 1 DESC
        """),
        params,
    ).fetchall()

    sale_data     = [{"month": str(r[0])[:7], "bills": r[1], "total": float(r[2] or 0)} for r in sale_rows]
    purchase_data = [{"month": str(r[0])[:7], "bills": r[1], "total": float(r[2] or 0)} for r in purchase_rows]

    scope = f"project {project_code}" if project_code else "all projects"
    system_prompt = (
        "You are a financial analyst for a construction/engineering ERP. "
        "Analyze the given 3-month sale and purchase data. "
        "Identify trends, flag any month with high purchase-to-sale ratio, "
        "and give 2-3 actionable insights. Be concise."
    )
    user_message = (
        f"Scope: {scope}\n\n"
        f"Sale bills (last 3 months):\n{sale_data}\n\n"
        f"Purchase bills (last 3 months):\n{purchase_data}\n\n"
        "Give me a financial health summary and key insights."
    )

    insight = ask_claude(system_prompt, user_message, max_tokens=800)
    return jsonify({
        "scope": scope,
        "sale_summary":     sale_data,
        "purchase_summary": purchase_data,
        "insight":          insight,
    }), 200


# ── Project Budget Insights ───────────────────────────────────────────────────

@ai_bp.route("/insights/project", methods=["POST"])
@jwt_required()
def project_budget_insights():
    """
    Body: { "project_code": "..." }
    Compares approved budget vs actual purchase spend per CC code.
    Claude flags overruns, high burn rates, and gives warnings.
    """
    data = request.get_json(silent=True) or {}
    project_code = data.get("project_code", "")

    if not project_code:
        return jsonify({"error": "project_code is required"}), 400

    # Approved budget for this project (latest approved budget)
    budget_row = db.session.execute(
        text("""
            SELECT bm.id, bm.budget_no, bm.budget_date,
                   bm.order_value_excl_gst, bm.grand_total, bm.workflow_status
            FROM budget_master bm
            WHERE bm.project_code = :pc
              AND bm.status = 'Active'
            ORDER BY bm.budget_date DESC
            LIMIT 1
        """),
        {"pc": project_code},
    ).fetchone()

    if not budget_row:
        return jsonify({"error": "No approved budget found for this project"}), 404

    budget_id = budget_row[0]

    # Budget items (planned cost per item)
    budget_items = db.session.execute(
        text("""
            SELECT item_name, unit, order_qty, rate, initial_amount, total_cost
            FROM budget_items
            WHERE budget_id = :bid
            ORDER BY sl_no
        """),
        {"bid": budget_id},
    ).fetchall()

    # Actual purchase spend per CC code for this project
    actual_spend = db.session.execute(
        text("""
            SELECT pbi.cc_code, pbi.cc_name,
                   COUNT(DISTINCT pbm.id) AS bill_count,
                   SUM(pbi.basic_amount)  AS actual_amount
            FROM purchase_bill_items pbi
            JOIN purchase_bill_master pbm ON pbm.id = pbi.purchase_bill_id
            WHERE pbm.project_code = :pc
              AND pbm.status = 'Active'
            GROUP BY pbi.cc_code, pbi.cc_name
            ORDER BY actual_amount DESC
        """),
        {"pc": project_code},
    ).fetchall()

    # Actual sale revenue for this project
    sale_revenue = db.session.execute(
        text("""
            SELECT SUM(total_invoice_amount) AS total_revenue, COUNT(*) AS bill_count
            FROM sale_bill_master
            WHERE project_code = :pc AND status = 'Active'
        """),
        {"pc": project_code},
    ).fetchone()

    budget_summary = {
        "budget_no":            budget_row[1],
        "budget_date":          str(budget_row[2]),
        "order_value_excl_gst": float(budget_row[3] or 0),
        "grand_total_budget":   float(budget_row[4] or 0),
        "workflow_status":      budget_row[5],
    }
    planned_items = [
        {
            "item": r[0], "unit": r[1],
            "qty": float(r[2] or 0), "rate": float(r[3] or 0),
            "planned_amount": float(r[4] or 0), "total_cost": float(r[5] or 0),
        }
        for r in budget_items
    ]
    actuals = [
        {
            "cc_code": r[0], "cc_name": r[1],
            "bills": r[2], "actual_spent": float(r[3] or 0),
        }
        for r in actual_spend
    ]
    total_actual_spend = sum(a["actual_spent"] for a in actuals)
    total_revenue      = float(sale_revenue[0] or 0) if sale_revenue else 0
    burn_pct = round(
        (total_actual_spend / budget_summary["grand_total_budget"] * 100), 1
    ) if budget_summary["grand_total_budget"] else 0

    system_prompt = (
        "You are a project financial controller for a construction/engineering ERP. "
        "Analyze the project's budget vs actual spend. "
        "Flag any CC code where actual spend has exceeded or is close to (>80%) planned cost. "
        "Calculate gross margin (revenue - spend). "
        "Give 3-4 bullet-point warnings or recommendations. Be concise and direct."
    )
    user_message = (
        f"Project: {project_code}\n\n"
        f"Budget summary: {budget_summary}\n"
        f"Total actual purchase spend: ₹{total_actual_spend:,.2f} ({burn_pct}% of budget)\n"
        f"Total sale revenue billed: ₹{total_revenue:,.2f}\n\n"
        f"Planned budget items:\n{planned_items}\n\n"
        f"Actual spend by CC code:\n{actuals}\n\n"
        "Give budget health analysis, flag overruns, and suggest actions."
    )

    insight = ask_claude(system_prompt, user_message, max_tokens=900)
    return jsonify({
        "project_code":       project_code,
        "budget_summary":     budget_summary,
        "total_actual_spend": total_actual_spend,
        "total_revenue":      total_revenue,
        "burn_percentage":    burn_pct,
        "actual_by_cc":       actuals,
        "insight":            insight,
    }), 200


def _get_module_summary(module: str) -> dict:
    if module == "finance":
        rows = db.session.execute(
            text("""
                SELECT
                    DATE_TRUNC('month', invoice_date) AS month,
                    COUNT(*) AS bill_count,
                    SUM(total_invoice_amount) AS total_amount
                FROM sale_bill_master
                WHERE status = 'Active'
                  AND invoice_date >= NOW() - INTERVAL '3 months'
                GROUP BY 1
                ORDER BY 1 DESC
            """)
        ).fetchall()
        return [{"month": str(r[0])[:7], "bills": r[1], "total": float(r[2] or 0)} for r in rows]

    if module == "hr":
        rows = db.session.execute(
            text("""
                SELECT department, COUNT(*) AS headcount
                FROM employees
                WHERE status = 'Active'
                GROUP BY department
                ORDER BY headcount DESC
                LIMIT 10
            """)
        ).fetchall()
        return [{"department": r[0], "headcount": r[1]} for r in rows]

    return {}
