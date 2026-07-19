import os
import json
import re
import requests
from .schema import get_schema_prompt

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


def parse_query(query: str) -> dict:
    if GROQ_API_KEY:
        try:
            return _groq_parse(query)
        except Exception:
            pass
    return _rule_based_parse(query)


def _groq_parse(query: str) -> dict:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": get_schema_prompt()},
            {"role": "user", "content": query},
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # extract JSON from response
    match = re.search(r"\{[\s\S]+\}", content)
    if not match:
        raise ValueError("No JSON in response")
    return json.loads(match.group())


def _rule_based_parse(query: str) -> dict:
    from datetime import datetime, timedelta

    q = query.lower()
    today = datetime.utcnow().date()

    # ── linked search detection ────────────────────────────────────
    # e.g. "GRNs linked to order ORD-2024-001" or "DCs for order ORD-001"
    linked_match = re.search(
        r"(?:linked to|for order|against order|of order)\s+([A-Za-z0-9/_-]+)",
        query, re.IGNORECASE
    )
    linked_order_no = linked_match.group(1).strip() if linked_match else None

    # ── document number detection ──────────────────────────────────
    # matches patterns like ORD-001, GRN-2024-05-001, IND/001 etc.
    doc_no_match = re.search(
        r"\b((?:ORD|GRN|IND|SRN|ENQ|DC|PW)[/_-][A-Za-z0-9/_-]+)\b",
        query, re.IGNORECASE
    )
    doc_no = doc_no_match.group(1).strip() if doc_no_match else None

    # ── detect module ──────────────────────────────────────────────
    module = "order"
    if "grn" in q or "goods receipt" in q:
        module = "grn"
    elif "indent" in q:
        module = "indent"
    elif "enquiry" in q:
        module = "enquiry"
    elif "srn" in q or "site return" in q:
        module = "srn"
    elif "delivery challan" in q or " dc " in q:
        module = "dc"
    elif "project work" in q or "pw order" in q:
        module = "pw_order"
    elif doc_no:
        prefix = doc_no.split("-")[0].split("/")[0].upper()
        prefix_map = {
            "GRN": "grn", "IND": "indent", "SRN": "srn",
            "ENQ": "enquiry", "DC": "dc", "PW": "pw_order", "ORD": "order"
        }
        module = prefix_map.get(prefix, "order")

    filters = []

    # ── linked order filter ────────────────────────────────────────
    if linked_order_no:
        filters.append({"field": "linked_order_no", "op": "eq", "value": linked_order_no})

    # ── document number filter ─────────────────────────────────────
    elif doc_no:
        doc_field_map = {
            "order": "order_no", "pw_order": "order_no", "grn": "grn_no",
            "indent": "indent_no", "enquiry": "enquiry_no",
            "srn": "srn_no", "dc": "dc_no",
        }
        filters.append({"field": doc_field_map.get(module, "order_no"), "op": "like", "value": doc_no})

    # ── status ─────────────────────────────────────────────────────
    for status in ["pending", "approved", "rejected", "draft", "submitted"]:
        if status in q:
            filters.append({"field": "workflow_status", "op": "eq", "value": status.capitalize()})
            break

    # ── amount range (between X and Y) ────────────────────────────
    range_match = re.search(
        r"between\s+(\d+(?:\.\d+)?)\s*(lakh|crore|k)?\s+and\s+(\d+(?:\.\d+)?)\s*(lakh|crore|k)?",
        q
    )
    if range_match and not doc_no and not linked_order_no:
        def _to_val(num, unit):
            v = float(num)
            if unit == "lakh":   v *= 100000
            elif unit == "crore": v *= 10000000
            elif unit == "k":    v *= 1000
            return v
        low = _to_val(range_match.group(1), range_match.group(2))
        high = _to_val(range_match.group(3), range_match.group(4))
        filters.append({"field": "total_amount", "op": "between", "value": [low, high]})
    else:
        # ── single amount ──────────────────────────────────────────
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(lakh|crore|k)?", q)
        if amount_match and not doc_no and not linked_order_no:
            val = float(amount_match.group(1))
            unit = amount_match.group(2)
            if unit == "lakh":   val *= 100000
            elif unit == "crore": val *= 10000000
            elif unit == "k":    val *= 1000
            op = "gt" if "above" in q or "more than" in q or "greater" in q else \
                 "lt" if "below" in q or "less than" in q else "gte"
            filters.append({"field": "total_amount", "op": op, "value": val})

    # ── approval level ─────────────────────────────────────────────
    level_match = re.search(r"(?:approval\s+level|level)\s+(\d+)", q)
    if level_match:
        filters.append({"field": "current_level", "op": "eq", "value": int(level_match.group(1))})

    # ── date ranges ────────────────────────────────────────────────
    date_field_map = {
        "order": "order_date", "pw_order": "order_date",
        "grn": "grn_date", "indent": "indent_date",
        "enquiry": "enquiry_date", "srn": "srn_date", "dc": "dc_date",
    }
    date_field = date_field_map.get(module, "order_date")

    if "last month" in q:
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        last = today.replace(day=1) - timedelta(days=1)
        filters.append({"field": date_field, "op": "between", "value": [str(first), str(last)]})
    elif "this month" in q:
        first = today.replace(day=1)
        filters.append({"field": date_field, "op": "between", "value": [str(first), str(today)]})
    elif "this week" in q:
        start = today - timedelta(days=today.weekday())
        filters.append({"field": date_field, "op": "between", "value": [str(start), str(today)]})
    elif "today" in q:
        filters.append({"field": date_field, "op": "eq", "value": str(today)})
    elif "yesterday" in q:
        filters.append({"field": date_field, "op": "eq", "value": str(today - timedelta(days=1))})

    return {
        "modules": [module],
        "filters": filters,
        "sort": {"field": date_field, "dir": "desc"},
        "limit": 50,
    }
