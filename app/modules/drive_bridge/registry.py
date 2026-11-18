"""Which ERP tables hold uploaded files, which project they belong to, and which
page permission lets someone see them. Used to show ERP documents in Edox Drive.

Add a row here when a new module starts storing files. Tables not listed are
never shown in Drive (on purpose: chat files, HR employee papers, CVs,
profile pictures and signatures stay private to the ERP).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    table: str
    file_columns: tuple
    keys: tuple                      # page permission keys; any of VIEW / EDIT / APPROVER on one is enough
    project_columns: tuple = ()      # empty = company-wide (not tied to a project)


SOURCES = (
    # ── project documents ────────────────────────────────────────
    Source("grn_master", ("attached_doc", "pdf_url"), ("goods_received_note",), ("project_code",)),
    Source("gin_master", ("attached_doc",), ("goods_issue_note",), ("project_code",)),
    Source("srn_master", ("attached_doc",), ("service_received_note",), ("project_code",)),
    Source("indent_master", ("supporting_file",), ("indent",), ("project_code",)),
    Source("enquiry_master", ("quotation_url",), ("enquiry",), ("project_code",)),
    Source("order_master", ("supporting_file", "pdf_url"), ("order", "material_order"), ("project_code",)),
    Source("pw_order_master", ("supporting_file",), ("order", "service_order"), ("project_code",)),
    Source("dlr_master", ("scan_copy",), ("dlr",), ("project_code",)),
    Source("dc_master", ("attached_doc",), ("delivery_challan",), ("from_project_code", "to_project_code")),
    Source("brr_master", ("attached_doc",), ("bill_receive_register",), ("project_code",)),
    Source("brg_master", ("attached_doc",), ("billing_by_grn", "bill_receive_register"), ("project_code",)),
    Source("brs_master", ("attached_doc",), ("billing_by_srn", "bill_receive_register"), ("project_code",)),
    Source("brb_master", ("attached_doc",), ("bill_receive_register",), ("project_code",)),
    Source("payment_request_master", ("attached_doc",), ("payment_request",), ("project_code",)),
    Source("billing_master", ("attachment",), ("sale_claim_bill", "sale_certified_bill", "sale"), ("project_code",)),
    Source("og_sale_order_master", ("attachment_1", "attachment_2", "attachment_3"), ("sale_order",), ("project_code",)),
    Source("hindrance_register", ("attachment",), ("hindrance_register",), ("project_code",)),
    Source("drawing_register", ("attachment",), ("drawing_register",), ("project_code",)),
    Source("concrete_registry", ("attach_batch_file",), ("concrete_register",), ("projectcode",)),
    Source("bbs_register", ("attachment",), ("bbs_register",), ("project_code",)),
    Source("petty_cash_budget", ("attachment",), ("petty_cash",), ("project_code",)),
    Source("petty_cash_docket_voucher", ("attachment",), ("petty_cash",), ("project_code",)),
    Source("site_photos", ("file_url",), ("daily_progress_report",), ("project_code",)),
    # ── company-wide documents ───────────────────────────────────
    Source("companies", ("pan_file", "gstn_file"), ("company_details",)),
    Source("vendors", ("trade_licence_file", "pan_file", "gstn_file", "bank_details_file"), ("ledger_code",)),
    Source("manpower_workers", ("aadhar_file", "pan_file", "uan_file", "esic_file", "bank_details_file"), ("labour_id",)),
    Source("pm_master", ("registration_file", "insurance_file", "puc_file", "road_tax_file", "purchased_bill_file"),
           ("pm_inventory",)),
    Source("pm_service_history", ("party_bill_file",), ("pm_inventory",)),
)

# Names shown for the top folders on disk (/srv/media/<folder>/…)
FOLDER_LABELS = {
    "grn": "GRN", "gin": "GIN", "srn": "SRN", "indent": "Indent", "enquiry": "Enquiry",
    "order": "Material Order", "order_pdf": "Order PDFs", "pw_order": "Service Order", "dlr": "DLR",
    "dc": "Delivery Challan", "brr": "Bill Receive Register", "billing": "Billing",
    "payment_request": "Payment Request", "og_sale_order": "Sale Order",
    "hindrance_register": "Hindrance Register", "drawing_register": "Drawing Register",
    "concrete_register": "Concrete Register", "bbs_register": "BBS Register", "petty_cash": "Petty Cash",
    "ledger": "Vendors", "manpower": "Labour", "company": "Company", "pm": "Plant & Machinery",
    "dpr": "Site Photos", "site_photos": "Site Photos",
}

COMPANY = "_company"          # the folder for company-wide documents
