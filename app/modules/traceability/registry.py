# app/modules/traceability/registry.py
"""
Single description of every document and line type the Traceability
Workbench understands, and of every relationship between them that
actually exists in the schema. Nothing here is inferred from item codes
or names.
"""

from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.models.dcMaster import DcMaster, DcItem
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster, BrbItem
from app.models.bvsMaster import BvsMaster, BvsItem
from app.models.bssMaster import BssMaster, BssItem
from app.models.purchaseBill import PurchaseBillMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster


# Lifecycle stages, in order (the "lanes" of the flow).
STAGES = [
    ("REQUISITION", "Requisition"),
    ("ORDERING", "Ordering"),
    ("RECEIPT", "Receipt"),
    ("INVENTORY", "Issue & Transfer"),
    ("BILLING", "Supplier Billing"),
    ("ACCOUNTS", "Accounts"),
    ("PAYMENT", "Payment"),
]
STAGE_INDEX = {k: i for i, (k, _) in enumerate(STAGES)}


# model, number / date / status columns, project columns, permission page codes,
# stage, flow ("MATERIAL" / "SERVICE" / "COMMON"), header amount column.
DOC_TYPES = {
    "INDENT": dict(
        label="Indent", model=IndentMaster, no="indent_no", date="indent_date",
        projects=("project_code",), pages=("indent",), stage="REQUISITION", flow="MATERIAL",
        line="INDENT_LINE", amount=None,
    ),
    "ORDER": dict(
        label="Material Order", model=OrderMaster, no="order_no", date="order_date",
        projects=("project_code",), pages=("order",), stage="ORDERING", flow="MATERIAL",
        line="ORD_LINE", amount="total_amount",
    ),
    "PW_ORDER": dict(
        label="Service Order", model=ProjectWorkOrderMaster, no="order_no", date="order_date",
        projects=("project_code",), pages=("order",), stage="ORDERING", flow="SERVICE",
        line="PW_LINE", amount="total_amount",
    ),
    "GRN": dict(
        label="GRN", model=GrnMaster, no="grn_no", date="grn_date",
        projects=("project_code",), pages=("goods_received_note",), stage="RECEIPT", flow="MATERIAL",
        line="GRN_LINE", amount=None,
    ),
    "SRN": dict(
        label="SRN", model=SrnMaster, no="srn_no", date="srn_date",
        projects=("project_code",), pages=("service_received_note", "goods_received_note"),
        stage="RECEIPT", flow="SERVICE", line="SRN_LINE", amount=None,
    ),
    "GIN": dict(
        label="GIN", model=GinMaster, no="gin_no", date="gin_date",
        projects=("project_code",), pages=("goods_issue_note",), stage="INVENTORY", flow="MATERIAL",
        line="GIN_LINE", amount=None,
    ),
    "DC": dict(
        label="Delivery Challan", model=DcMaster, no="dc_no", date="challan_date",
        projects=("from_project_code", "to_project_code"), pages=("delivery_challan",),
        stage="INVENTORY", flow="MATERIAL", line="DC_LINE", amount=None,
    ),
    "BRR": dict(
        label="Bill Receive Register", model=BrrMaster, no="brr_no", date="brr_date",
        projects=("project_code",), pages=("bill_receive_register",), stage="BILLING", flow="COMMON",
        line=None, amount="total_amount",
    ),
    "BRB": dict(
        label="BRR Billing (BRB)", model=BrbMaster, no="brb_no", date="brb_date",
        projects=("project_code",), pages=("bill_receive_register",), stage="BILLING", flow="COMMON",
        line="BRB_LINE", amount="total_amount",
    ),
    "BVS": dict(
        label="Vendor Billing GRN (legacy)", model=BvsMaster, no="bvs_no", date="bvs_date",
        projects=("project_code",), pages=("bill_receive_register",), stage="BILLING", flow="MATERIAL",
        line="BVS_LINE", amount="total_amount", legacy=True,
    ),
    "BSS": dict(
        label="Vendor Billing SRN (legacy)", model=BssMaster, no="bss_no", date="bss_date",
        projects=("project_code",), pages=("bill_receive_register",), stage="BILLING", flow="SERVICE",
        line="BSS_LINE", amount="total_amount", legacy=True,
    ),
    "PURCHASE_BILL": dict(
        label="Purchase Bill", model=PurchaseBillMaster, no="purchase_bill_no", date="processing_date",
        projects=("project_code",), pages=("purchases",), stage="ACCOUNTS", flow="COMMON",
        line=None, amount="total_invoice_amount",
    ),
    "BILL_PAYMENT": dict(
        label="Bill Payment", model=BillPaymentReceiptMaster, no="receipt_no", date="payment_date",
        projects=("project_code",), pages=("payment",), stage="PAYMENT", flow="COMMON",
        line=None, amount="total_invoice_amount",
    ),
}


# Line tables: model, header FK column, owning document type, quantity column.
LINE_TYPES = {
    "INDENT_LINE": dict(model=IndentItem, header="indent_id", doc="INDENT", qty="qty"),
    "ORD_LINE": dict(model=OrderItem, header="order_id", doc="ORDER", qty="qty"),
    "PW_LINE": dict(model=ProjectWorkOrderItem, header="order_id", doc="PW_ORDER", qty="qty"),
    "GRN_LINE": dict(model=GrnItem, header="grn_id", doc="GRN", qty="current_received_qty"),
    "SRN_LINE": dict(model=SrnItem, header="srn_id", doc="SRN", qty="current_received_qty"),
    "GIN_LINE": dict(model=GinItem, header="gin_id", doc="GIN", qty="issue_qty"),
    "DC_LINE": dict(model=DcItem, header="dc_id", doc="DC", qty="issue_qty"),
    "BRB_LINE": dict(model=BrbItem, header="brb_id", doc="BRB", qty="billing_qty"),
    "BVS_LINE": dict(model=BvsItem, header="bvs_id", doc="BVS", qty="billing_qty"),
    "BSS_LINE": dict(model=BssItem, header="bss_id", doc="BSS", qty="billing_qty"),
}


# Exact item-level links: (child line type, FK column on child, parent line type, meaning).
LINE_LINKS = [
    ("ORD_LINE", "indent_item_id", "INDENT_LINE", "Ordered"),
    ("GRN_LINE", "order_item_id", "ORD_LINE", "Received"),
    ("GIN_LINE", "order_item_id", "ORD_LINE", "Issued"),
    ("DC_LINE", "order_item_id", "ORD_LINE", "Dispatched"),
    ("SRN_LINE", "pw_order_item_id", "PW_LINE", "Received"),
    ("BRB_LINE", "grn_item_id", "GRN_LINE", "Billed"),
    ("BRB_LINE", "srn_item_id", "SRN_LINE", "Billed"),
    ("BVS_LINE", "grn_item_id", "GRN_LINE", "Billed (legacy)"),
    ("BSS_LINE", "srn_item_id", "SRN_LINE", "Billed (legacy)"),
]

# Header-only links: (child doc type, FK column on child, parent doc type, link kind, meaning).
#   ORDER_LEVEL : relates to the order as a whole, not to particular lines
#   HEADER      : exact document-to-document link
HEADER_LINKS = [
    ("BRR", "order_id", "ORDER", "ORDER_LEVEL", "Bill received"),
    ("BRR", "pw_order_id", "PW_ORDER", "ORDER_LEVEL", "Bill received"),
    ("BRB", "brr_id", "BRR", "HEADER", "Reconciled"),
    ("PURCHASE_BILL", "brr_id", "BRR", "HEADER", "Booked"),
    ("BILL_PAYMENT", "purchase_bill_id", "PURCHASE_BILL", "HEADER", "Paid"),
]


def doc_projects(doc_type, row):
    return [getattr(row, c, None) for c in DOC_TYPES[doc_type]["projects"]]
