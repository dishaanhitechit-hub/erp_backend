from datetime import datetime

MODULES = {
    "order": {
        "table": "order_master",
        "label": "Purchase Order / Work Order / Service Order",
        "item_table": "order_items",
        "item_fk": "order_id",
        "fields": {
            "order_no":        {"type": "string",  "label": "Order Number"},
            "workflow_status": {"type": "enum",    "label": "Status", "values": ["Draft", "Submitted", "Approved", "Rejected", "Reback"]},
            "total_amount":    {"type": "number",  "label": "Total Amount"},
            "basic_amount":    {"type": "number",  "label": "Basic Amount"},
            "order_date":      {"type": "date",    "label": "Order Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "vendor_id":       {"type": "number",  "label": "Vendor ID"},
            "category_code":   {"type": "string",  "label": "Category"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "current_level":   {"type": "number",  "label": "Current Approval Level"},
        },
        "virtual_fields": {
            "project_name": "project_code",
            "vendor_name":  "vendor_id",
            "item_name":    "__item__",
            "creator_name": "created_by",
            "vendor_names": "__multi_vendor__",
            "project_names":"__multi_project__",
        }
    },
    "pw_order": {
        "table": "pw_order_master",
        "label": "Project Work Order",
        "item_table": "pw_order_items",
        "item_fk": "order_id",
        "fields": {
            "order_no":        {"type": "string",  "label": "Order Number"},
            "workflow_status": {"type": "enum",    "label": "Status", "values": ["Draft", "Submitted", "Approved", "Rejected", "Reback"]},
            "total_amount":    {"type": "number",  "label": "Total Amount"},
            "order_date":      {"type": "date",    "label": "Order Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "vendor_id":       {"type": "number",  "label": "Vendor ID"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "current_level":   {"type": "number",  "label": "Current Approval Level"},
        },
        "virtual_fields": {
            "project_name":  "project_code",
            "vendor_name":   "vendor_id",
            "item_name":     "__item__",
            "creator_name":  "created_by",
            "vendor_names":  "__multi_vendor__",
            "project_names": "__multi_project__",
        }
    },
    "grn": {
        "table": "grn_master",
        "label": "Goods Receipt Note",
        "item_table": "grn_items",
        "item_fk": "grn_id",
        "linked_order_table": "order_master",
        "linked_order_fk": "order_id",
        "linked_order_no_field": "order_no",
        "fields": {
            "grn_no":          {"type": "string",  "label": "GRN Number"},
            "workflow_status": {"type": "enum",    "label": "Status", "values": ["Draft", "Submitted", "Approved", "Rejected"]},
            "grn_date":        {"type": "date",    "label": "GRN Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "vendor_id":       {"type": "number",  "label": "Vendor ID"},
            "total_amount":    {"type": "number",  "label": "Total Amount"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "order_id":        {"type": "number",  "label": "Linked Order ID"},
            "current_level":   {"type": "number",  "label": "Current Approval Level"},
        },
        "virtual_fields": {
            "project_name":    "project_code",
            "vendor_name":     "vendor_id",
            "item_name":       "__item__",
            "creator_name":    "created_by",
            "linked_order_no": "__linked_order__",
            "vendor_names":    "__multi_vendor__",
            "project_names":   "__multi_project__",
        }
    },
    "indent": {
        "table": "indent_master",
        "label": "Material Indent",
        "item_table": "indent_items",
        "item_fk": "indent_id",
        "fields": {
            "indent_no":       {"type": "string",  "label": "Indent Number"},
            "workflow_status": {"type": "enum",    "label": "Status", "values": ["Draft", "Submitted", "Approved", "Rejected"]},
            "indent_date":     {"type": "date",    "label": "Indent Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "current_level":   {"type": "number",  "label": "Current Approval Level"},
        },
        "virtual_fields": {
            "project_name":  "project_code",
            "item_name":     "__item__",
            "creator_name":  "created_by",
            "project_names": "__multi_project__",
        }
    },
    "enquiry": {
        "table": "enquiry_master",
        "label": "Enquiry",
        "item_table": "enquiry_item",
        "item_fk": "enquiry_id",
        "fields": {
            "enquiry_no":      {"type": "string",  "label": "Enquiry Number"},
            "workflow_status": {"type": "enum",    "label": "Status"},
            "enquiry_date":    {"type": "date",    "label": "Enquiry Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
        },
        "virtual_fields": {
            "project_name":  "project_code",
            "item_name":     "__item__",
            "creator_name":  "created_by",
            "project_names": "__multi_project__",
        }
    },
    "srn": {
        "table": "srn_master",
        "label": "Site Return Note",
        "item_table": "srn_items",
        "item_fk": "srn_id",
        "linked_order_table": "pw_order_master",
        "linked_order_fk": "order_id",
        "linked_order_no_field": "order_no",
        "fields": {
            "srn_no":          {"type": "string",  "label": "SRN Number"},
            "workflow_status": {"type": "enum",    "label": "Status"},
            "srn_date":        {"type": "date",    "label": "SRN Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "order_id":        {"type": "number",  "label": "Linked PW Order ID"},
        },
        "virtual_fields": {
            "project_name":    "project_code",
            "item_name":       "__item__",
            "creator_name":    "created_by",
            "linked_order_no": "__linked_order__",
        }
    },
    "dc": {
        "table": "dc_master",
        "label": "Delivery Challan",
        "item_table": "dc_items",
        "item_fk": "dc_id",
        "linked_order_table": "order_master",
        "linked_order_fk": "order_id",
        "linked_order_no_field": "order_no",
        "fields": {
            "dc_no":           {"type": "string",  "label": "DC Number"},
            "workflow_status": {"type": "enum",    "label": "Status"},
            "dc_date":         {"type": "date",    "label": "DC Date"},
            "project_code":    {"type": "string",  "label": "Project Code"},
            "created_by":      {"type": "number",  "label": "Created By (User ID)"},
            "order_id":        {"type": "number",  "label": "Linked Order ID"},
        },
        "virtual_fields": {
            "project_name":    "project_code",
            "item_name":       "__item__",
            "creator_name":    "created_by",
            "linked_order_no": "__linked_order__",
        }
    },
}

ALL_MODULES = list(MODULES.keys())


def get_schema_prompt():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = [
        f"Today's date is {today}.",
        "You are a query parser for an ERP system. Convert the user's natural language query into a JSON object.",
        "Available modules and their fields:",
    ]
    for mod, meta in MODULES.items():
        lines.append(f"\nModule: {mod} ({meta['label']})")
        for field, info in meta["fields"].items():
            extra = ""
            if info["type"] == "enum" and "values" in info:
                extra = f" — values: {info['values']}"
            lines.append(f"  - {field} ({info['type']}): {info['label']}{extra}")
        lines.append(f"  Virtual filters (resolve by name, not ID):")
        for vf in meta.get("virtual_fields", {}):
            lines.append(f"  - {vf} (string): use this when user mentions a name")

    lines += [
        "\nOutput ONLY valid JSON in this exact format:",
        """
{
  "modules": ["<module1>", "<module2>"],
  "filters": [
    {"field": "<field_or_virtual_field>", "op": "<eq|gt|lt|gte|lte|like|between|in>", "value": <value>}
  ],
  "sort": {"field": "<field>", "dir": "<asc|desc>"},
  "limit": 50
}""",
        "\nRules:",
        "- 'modules' is always a list. Put one module or multiple if the query spans multiple.",
        "- Use 'all' in modules list to search all modules.",
        "- Resolve relative dates like 'last month', 'this week', 'yesterday' to absolute dates using today's date.",
        "- For 'between' op, value must be a list of two dates: [start, end].",
        "- Amount values like '5 lakh' = 500000, '1 crore' = 10000000.",
        "- For project name, vendor name, item name, creator name — use the virtual field name with 'like' op and the name string as value.",
        "- If no sort is mentioned, sort by the primary date field desc.",
        "- Output only the JSON, no explanation.",
        "\nExamples:",
        '- "pending purchase orders above 5 lakh last month" → modules: ["order"], filters: [{workflow_status eq Pending}, {total_amount gt 500000}, {order_date between [...]}]',
        '- "GRNs for Project Sunrise this week" → modules: ["grn"], filters: [{project_name like "Sunrise"}, {grn_date between [...]}]',
        '- "orders created by Rahul" → modules: ["order"], filters: [{creator_name like "Rahul"}]',
        '- "show orders and GRNs both from last month" → modules: ["order", "grn"], filters: [{order_date/grn_date between [...]}]',
        '- "indents containing steel this month" → modules: ["indent"], filters: [{item_name like "steel"}, {indent_date between [...]}]',
        '- "show GRNs linked to order ORD-2024-001" → modules: ["grn"], filters: [{linked_order_no eq "ORD-2024-001"}]',
        '- "DCs against order ORD-001" → modules: ["dc"], filters: [{linked_order_no eq "ORD-001"}]',
        '- "show order ORD-2024-005" → modules: ["order"], filters: [{order_no like "ORD-2024-005"}]',
        '- "find GRN GRN-2024-003" → modules: ["grn"], filters: [{grn_no like "GRN-2024-003"}]',
        '- "orders between 2 lakh and 5 lakh" → modules: ["order"], filters: [{total_amount between [200000, 500000]}]',
        '- "orders at approval level 2" → modules: ["order"], filters: [{current_level eq 2}]',
        '- "orders from vendor ABC or vendor XYZ" → modules: ["order"], filters: [{vendor_names like ["ABC", "XYZ"]}]',
        '- "orders for Project Sunrise or Project Alpha" → modules: ["order"], filters: [{project_names like ["Sunrise", "Alpha"]}]',
    ]
    return "\n".join(lines)
