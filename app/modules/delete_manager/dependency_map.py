"""
dependency_map.py
─────────────────
Defines the complete downstream dependency chain for every module.

For each module we define:
  - how to look up the record
  - which child tables / FK columns point at it
  - what each child's "module_code" is (for notifications)
  - a label describing the child (for WA message text)

Structure per entry:
{
    "model_class":  <SQLAlchemy model class>,
    "doc_no_field": "<field name to use as human-readable number>",
    "project_field": "<field name for project_code>",   # or None
    "children": [
        {
            "child_model":   <SQLAlchemy model class>,
            "fk_column":     "<column on child that references parent PK>",
            "doc_no_field":  "<child's human-readable number field>",
            "module_code":   "<module code for WA notification>",
            "label":         "<human-readable child type name>",
        },
        ...
    ]
}
"""

# ── Models ─────────────────────────────────────────────────────────────────
from app.models.indent_master      import IndentMaster
from app.models.orderMaster        import OrderMaster
from app.models.ORDER_projectwork  import ProjectWorkOrderMaster
from app.models.grnMaster          import GrnMaster
from app.models.srnMaster          import SrnMaster
from app.models.ginMaster          import GinMaster
from app.models.dcMaster           import DcMaster
from app.models.dlrMaster          import DlrMaster
from app.models.bvsMaster          import BvsMaster
from app.models.bssMaster          import BssMaster
from app.models.brrMaster          import BrrMaster
from app.models.brgMaster          import BrgMaster, BrgItem
from app.models.brsMaster          import BrsMaster, BrsItem
from app.models.brbMaster          import BrbMaster, BrbItem
from app.models.purchaseBill       import PurchaseBillMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.purchaseVoucher    import PurchaseVoucherMaster
from app.models.paymentVoucher     import PaymentVoucherMaster
from app.models.saleBill           import SaleBillMaster
from app.models.saleReceipt        import SaleReceiptMaster
from app.models.saleReceiptBilling import SaleReceiptBillingMaster
from app.models.billingMaster      import BillingMaster, BillingBoqItem
from app.models.ogSaleOrder        import OgSaleOrderMaster
from app.models.enquiry_master     import EnquiryMaster
from app.models.batchingPlant      import BatchingPlantMaster
from app.models.pettyCashBudget    import PettyCashBudget
from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher
from app.models.journalEntry       import JournalEntryMaster
from app.models.contraEntry        import ContraEntryMaster
from app.models.creditNote         import CreditNoteMaster
from app.models.debitNote          import DebitNoteMaster
from app.models.bbsRegister        import BbsRegister
from app.models.drawingRegister    import DrawingRegister
from app.models.hindranceRegister  import HindranceRegister
from app.models.concrete_registry  import ConcreteRegistry
from app.models.uncertainAllocation import UncertainAllocationMaster


DEPENDENCY_MAP = {

    # ══════════════════════════════════════════════════════════════════
    # PROCUREMENT — MATERIALS
    # ══════════════════════════════════════════════════════════════════

    "INDENT": {
        "model_class":  IndentMaster,
        "doc_no_field": "indent_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  EnquiryMaster,
                "fk_column":    "indent_id",
                "doc_no_field": "enquiry_no",
                "module_code":  "ENQUIRY",
                "label":        "Enquiry",
            },
            # Orders reference indent via order_items.indent_item_id
            # We check OrderMaster through the IndentItem → OrderItem join
            # This is handled specially in the service (see _check_indent_orders)
        ],
        "special_checks": ["indent_orders"],
    },

    "ENQUIRY": {
        "model_class":  EnquiryMaster,
        "doc_no_field": "enquiry_no",
        "project_field": "project_code",
        "children": [],   # leaf — orders don't FK directly to enquiry
    },

    "ORDER": {
        "model_class":  OrderMaster,
        "doc_no_field": "order_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  GrnMaster,
                "fk_column":    "order_id",
                "doc_no_field": "grn_no",
                "module_code":  "GRN",
                "label":        "GRN (Goods Receipt Note)",
            },
            {
                "child_model":  GinMaster,
                "fk_column":    "order_id",
                "doc_no_field": "gin_no",
                "module_code":  "GIN",
                "label":        "GIN (Goods Issue Note)",
            },
            {
                "child_model":  DcMaster,
                "fk_column":    "order_id",
                "doc_no_field": "dc_no",
                "module_code":  "DC",
                "label":        "DC (Delivery Challan)",
            },
            {
                "child_model":  DlrMaster,
                "fk_column":    "order_id",
                "doc_no_field": "dlr_no",
                "module_code":  "DLR",
                "label":        "DLR (Daily Labour Report)",
            },
            {
                "child_model":  BvsMaster,
                "fk_column":    "order_id",
                "doc_no_field": "bvs_no",
                "module_code":  "BVS",
                "label":        "BVS (Vendor Billing GRN)",
            },
            {
                "child_model":  BrrMaster,
                "fk_column":    "order_id",
                "doc_no_field": "brr_no",
                "module_code":  "BRR",
                "label":        "BRR (Bill Receive Register)",
            },
            {
                "child_model":  PurchaseBillMaster,
                "fk_column":    "order_id",
                "doc_no_field": "purchase_bill_no",
                "module_code":  "PURCHASE_BILL",
                "label":        "Purchase Bill",
            },
        ],
    },

    "PW_ORDER": {
        "model_class":  ProjectWorkOrderMaster,
        "doc_no_field": "order_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  SrnMaster,
                "fk_column":    "order_id",
                "doc_no_field": "srn_no",
                "module_code":  "SRN",
                "label":        "SRN (Service Receipt Note)",
            },
            {
                "child_model":  BssMaster,
                "fk_column":    "order_id",
                "doc_no_field": "bss_no",
                "module_code":  "BSS",
                "label":        "BSS (Vendor Billing SRN)",
            },
            {
                "child_model":  BrrMaster,
                "fk_column":    "pw_order_id",
                "doc_no_field": "brr_no",
                "module_code":  "BRR",
                "label":        "BRR (Bill Receive Register)",
            },
            {
                "child_model":  PurchaseBillMaster,
                "fk_column":    "pw_order_id",
                "doc_no_field": "purchase_bill_no",
                "module_code":  "PURCHASE_BILL",
                "label":        "Purchase Bill",
            },
            {
                "child_model":  BatchingPlantMaster,
                "fk_column":    "pw_order_id",
                "doc_no_field": "despatch_no",
                "module_code":  "BATCHING_PLANT",
                "label":        "Batching Plant Record",
            },
        ],
    },

    "GRN": {
        "model_class":  GrnMaster,
        "doc_no_field": "grn_no",
        "project_field": "project_code",
        "children": [],
        # BRG items and BRB items reference GRN at the item level.
        # Handled via special_checks to find parent BRG/BRB docs.
        "special_checks": ["grn_billing"],
    },

    "SRN": {
        "model_class":  SrnMaster,
        "doc_no_field": "srn_no",
        "project_field": "project_code",
        "children": [],
        "special_checks": ["srn_billing"],
    },

    "GIN": {
        "model_class":  GinMaster,
        "doc_no_field": "gin_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "DC": {
        "model_class":  DcMaster,
        "doc_no_field": "dc_no",
        "project_field": "to_project_code",
        "children": [],  # leaf
    },

    "DLR": {
        "model_class":  DlrMaster,
        "doc_no_field": "dlr_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "BVS": {
        "model_class":  BvsMaster,
        "doc_no_field": "bvs_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "BSS": {
        "model_class":  BssMaster,
        "doc_no_field": "bss_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # BILLING
    # ══════════════════════════════════════════════════════════════════

    "BRR": {
        "model_class":  BrrMaster,
        "doc_no_field": "brr_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  BrgMaster,
                "fk_column":    "brr_id",
                "doc_no_field": "brg_no",
                "module_code":  "BRG",
                "label":        "BRG (BRR Billing GRN)",
            },
            {
                "child_model":  BrsMaster,
                "fk_column":    "brr_id",
                "doc_no_field": "brs_no",
                "module_code":  "BRS",
                "label":        "BRS (BRR Billing SRN)",
            },
            {
                "child_model":  BrbMaster,
                "fk_column":    "brr_id",
                "doc_no_field": "brb_no",
                "module_code":  "BRB",
                "label":        "BRB (BRR Billing)",
            },
            {
                "child_model":  PurchaseBillMaster,
                "fk_column":    "brr_id",
                "doc_no_field": "purchase_bill_no",
                "module_code":  "PURCHASE_BILL",
                "label":        "Purchase Bill",
            },
        ],
    },

    "BRG": {
        "model_class":  BrgMaster,
        "doc_no_field": "brg_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "BRS": {
        "model_class":  BrsMaster,
        "doc_no_field": "brs_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "BRB": {
        "model_class":  BrbMaster,
        "doc_no_field": "brb_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # FINANCE — PURCHASE SIDE
    # ══════════════════════════════════════════════════════════════════

    "PURCHASE_BILL": {
        "model_class":  PurchaseBillMaster,
        "doc_no_field": "purchase_bill_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  BillPaymentReceiptMaster,
                "fk_column":    "purchase_bill_id",
                "doc_no_field": "receipt_no",
                "module_code":  "BILL_PAYMENT",
                "label":        "Bill Payment Receipt",
            },
        ],
    },

    "BILL_PAYMENT": {
        "model_class":  BillPaymentReceiptMaster,
        "doc_no_field": "receipt_no",
        "project_field": "project_code",
        "children": [],  # leaf — deepest node in procurement chain
    },

    "PURCHASE_VOUCHER": {
        "model_class":  PurchaseVoucherMaster,
        "doc_no_field": "voucher_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  PaymentVoucherMaster,
                "fk_column":    "purchase_voucher_id",
                "doc_no_field": "payment_vouch_no",
                "module_code":  "PAYMENT_VOUCHER",
                "label":        "Payment Voucher",
            },
        ],
    },

    "PAYMENT_VOUCHER": {
        "model_class":  PaymentVoucherMaster,
        "doc_no_field": "payment_vouch_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # FINANCE — SALES SIDE
    # ══════════════════════════════════════════════════════════════════

    "SALE_BILL": {
        "model_class":  SaleBillMaster,
        "doc_no_field": "sale_bill_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  SaleReceiptBillingMaster,
                "fk_column":    "certified_bill_id",    # SRB links via certified_bill_id
                "doc_no_field": "srb_no",
                "module_code":  "SALE_RECEIPT_BILLING",
                "label":        "Sale Receipt Billing",
            },
        ],
    },

    "SALE_RECEIPT": {
        "model_class":  SaleReceiptMaster,
        "doc_no_field": "receipt_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  SaleReceiptBillingMaster,
                "fk_column":    "receipt_id",
                "doc_no_field": "srb_no",
                "module_code":  "SALE_RECEIPT_BILLING",
                "label":        "Sale Receipt Billing",
            },
        ],
    },

    "SALE_RECEIPT_BILLING": {
        "model_class":  SaleReceiptBillingMaster,
        "doc_no_field": "srb_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # FINANCE — PETTY CASH
    # ══════════════════════════════════════════════════════════════════

    "PETTY_CASH_BUDGET": {
        "model_class":  PettyCashBudget,
        "doc_no_field": "id",            # budget has no doc_no, use id
        "project_field": "project_code",
        "children": [
            {
                "child_model":  PettyCashDocketVoucher,
                "fk_column":    "budget_id",
                "doc_no_field": "voucher_no",
                "module_code":  "PETTY_CASH_VOUCHER",
                "label":        "Petty Cash Docket Voucher",
            },
        ],
    },

    "PETTY_CASH_VOUCHER": {
        "model_class":  PettyCashDocketVoucher,
        "doc_no_field": "voucher_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # FINANCE — STANDALONE
    # ══════════════════════════════════════════════════════════════════

    "JOURNAL_ENTRY": {
        "model_class":  JournalEntryMaster,
        "doc_no_field": "voucher_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "CONTRA_ENTRY": {
        "model_class":  ContraEntryMaster,
        "doc_no_field": "voucher_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    "CREDIT_NOTE": {
        "model_class":  CreditNoteMaster,
        "doc_no_field": "credit_note_no",
        "project_field": "project_code",
        "children": [],  # leaf — references bill/order by string only
    },

    "DEBIT_NOTE": {
        "model_class":  DebitNoteMaster,
        "doc_no_field": "debit_note_no",
        "project_field": "project_code",
        "children": [],  # leaf — references bill/order by string only
    },

    # ══════════════════════════════════════════════════════════════════
    # PROJECT MGMT — SALES
    # ══════════════════════════════════════════════════════════════════

    "OG_SALE_ORDER": {
        "model_class":  OgSaleOrderMaster,
        "doc_no_field": "og_sale_order_no",
        "project_field": "project_code",
        "children": [
            {
                "child_model":  BillingMaster,
                "fk_column":    "og_sale_order_id",
                "doc_no_field": "billing_no",
                "module_code":  "BILLING",
                "label":        "Sale Claim / Certified Bill",
            },
            {
                "child_model":  SaleBillMaster,
                "fk_column":    "sale_order_id",
                "doc_no_field": "sale_bill_no",
                "module_code":  "SALE_BILL",
                "label":        "Sale Bill",
            },
            {
                "child_model":  SaleReceiptBillingMaster,
                "fk_column":    "og_sale_order_id",
                "doc_no_field": "srb_no",
                "module_code":  "SALE_RECEIPT_BILLING",
                "label":        "Sale Receipt Billing",
            },
        ],
    },

    "BILLING": {
        "model_class":  BillingMaster,
        "doc_no_field": "billing_no",
        "project_field": "project_code",
        # Item rows with no ORM cascade — removed together with the bill
        # (same as custom_billing delete_billing does).
        "delete_first": [(BillingBoqItem, "billing_id")],
        "children": [
            # Certified bills reference their claim bill via claim_bill_id (self-FK)
            {
                "child_model":  BillingMaster,
                "fk_column":    "claim_bill_id",
                "doc_no_field": "billing_no",
                "module_code":  "BILLING",
                "label":        "Certified Bill",
            },
            {
                "child_model":  SaleBillMaster,
                "fk_column":    "certified_bill_id",
                "doc_no_field": "sale_bill_no",
                "module_code":  "SALE_BILL",
                "label":        "Sale Bill",
            },
            {
                "child_model":  SaleReceiptBillingMaster,
                "fk_column":    "certified_bill_id",
                "doc_no_field": "srb_no",
                "module_code":  "SALE_RECEIPT_BILLING",
                "label":        "Sale Receipt Billing",
            },
        ],
    },

    "UNCERTAIN_ALLOCATION": {
        "model_class":  UncertainAllocationMaster,
        "doc_no_field": "ua_no",
        "project_field": "project_code",
        "children": [],  # leaf
    },

    # ══════════════════════════════════════════════════════════════════
    # PROJECT MGMT REGISTERS — all standalone
    # ══════════════════════════════════════════════════════════════════

    "BBS_REGISTER": {
        "model_class":  BbsRegister,
        "doc_no_field": "bbs_no",
        "project_field": "project_code",
        "children": [],
    },

    "DRAWING_REGISTER": {
        "model_class":  DrawingRegister,
        "doc_no_field": "dr_no",
        "project_field": "project_code",
        "children": [],
    },

    "HINDRANCE_REGISTER": {
        "model_class":  HindranceRegister,
        "doc_no_field": "hindrance_no",
        "project_field": "project_code",
        "children": [],
    },

    "CONCRETE_REGISTRY": {
        "model_class":  ConcreteRegistry,
        "doc_no_field": "id",
        "project_field": "projectcode",
        "children": [],
    },

    "BATCHING_PLANT": {
        "model_class":  BatchingPlantMaster,
        "doc_no_field": "despatch_no",
        "project_field": "project_code",
        "children": [],
    },
}


# ── Human-readable module names for WA messages ───────────────────────────
MODULE_DISPLAY_NAMES = {
    "INDENT":               "Indent",
    "ENQUIRY":              "Enquiry",
    "ORDER":                "Purchase Order",
    "PW_ORDER":             "Project Work Order",
    "GRN":                  "GRN",
    "SRN":                  "SRN",
    "GIN":                  "GIN",
    "DC":                   "Delivery Challan",
    "DLR":                  "Daily Labour Report",
    "BVS":                  "Vendor Billing (GRN)",
    "BSS":                  "Vendor Billing (SRN)",
    "BRR":                  "Bill Receive Register",
    "BRG":                  "BRR Billing (GRN)",
    "BRS":                  "BRR Billing (SRN)",
    "BRB":                  "BRR Billing",
    "PURCHASE_BILL":        "Purchase Bill",
    "BILL_PAYMENT":         "Bill Payment Receipt",
    "PURCHASE_VOUCHER":     "Purchase Voucher",
    "PAYMENT_VOUCHER":      "Payment Voucher",
    "SALE_BILL":            "Sale Bill",
    "SALE_RECEIPT":         "Sale Receipt",
    "SALE_RECEIPT_BILLING": "Sale Receipt Billing",
    "OG_SALE_ORDER":        "OG Sale Order",
    "BILLING":              "Billing (Claim/Certified)",
    "UNCERTAIN_ALLOCATION": "Uncertain Allocation",
    "PETTY_CASH_BUDGET":    "Petty Cash Budget",
    "PETTY_CASH_VOUCHER":   "Petty Cash Voucher",
    "JOURNAL_ENTRY":        "Journal Entry",
    "CONTRA_ENTRY":         "Contra Entry",
    "CREDIT_NOTE":          "Credit Note",
    "DEBIT_NOTE":           "Debit Note",
    "BBS_REGISTER":         "BBS Register",
    "DRAWING_REGISTER":     "Drawing Register",
    "HINDRANCE_REGISTER":   "Hindrance Register",
    "CONCRETE_REGISTRY":    "Concrete Registry",
    "BATCHING_PLANT":       "Batching Plant",
}


def get_display_name(module_code: str) -> str:
    return MODULE_DISPLAY_NAMES.get(module_code, module_code.replace("_", " ").title())
