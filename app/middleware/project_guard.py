"""Project permission guard for write APIs.

Every POST / PUT / PATCH / DELETE under a project-scoped module needs
`<page_code>.EDIT` in the project the record belongs to, as saved in
Settings > Role & Designation (project_designation_permissions merged with
project_user_permissions, via get_user_permissions).

Which project?
  * URL has a record id (edit/submit/delete/...): the project stored on that
    record. The payload cannot fake it.
  * Otherwise (create, bulk import): `projectCode` from the form / JSON body.

Not checked here:
  * GET requests (list / details / lookups) — intentionally left for later.
  * approve / reject / reback — already checked against the project's
    approval path (is_current_approver).
  * super_admin.

Company-wide accounting setup (financial year, historical posting, GST fix)
is admin / super_admin only (ADMIN_ONLY).
"""
import importlib

from flask import request
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

from app.response import res

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# URL segments whose own approver check already covers project access.
APPROVAL_ACTIONS = {"approve", "reject", "reback"}

# url prefix -> (allowed page codes (EDIT on any one is enough), "module:Model", project attr)
# Longest prefix wins, so sub-paths listed separately override their parent.
RULES = {
    # ---- Resources ----
    "/resource/indent":       (("indent",), "indent_master:IndentMaster", "project_code"),
    "/resource/enquiry":      (("enquiry",), "enquiry_master:EnquiryMaster", "project_code"),
    "/resource/order":        (("order",), "orderMaster:OrderMaster", "project_code"),
    "/resource/pw-order":     (("order",), "ORDER_projectwork:ProjectWorkOrderMaster", "project_code"),
    "/resource/grn":          (("goods_received_note",), "grnMaster:GrnMaster", "project_code"),
    "/resource/gin":          (("goods_issue_note",), "ginMaster:GinMaster", "project_code"),
    "/resource/srn":          (("service_received_note",), "srnMaster:SrnMaster", "project_code"),
    "/resource/bvs":          (("bill_receive_register",), "bvsMaster:BvsMaster", "project_code"),
    "/resource/bss":          (("bill_receive_register",), "bssMaster:BssMaster", "project_code"),
    "/resource/dc":           (("delivery_challan",), "dcMaster:DcMaster", "to_project_code"),
    "/resource/dlr":          (("dlr",), "dlrMaster:DlrMaster", "project_code"),
    "/resource/batching":     (("batching_plant",), "batchingPlant:BatchingPlantMaster", "project_code"),
    "/resource/machinery/log-book":  (("log_sheet",), "machineryLogBook:MachineryLogBook", "project_code"),
    "/resource/machinery/log-entry": (("log_sheet",), "machineryLogBook:LogBookEntry", "project_code"),
    # ---- Billing ----
    "/billing/brr":             (("bill_receive_register",), "brrMaster:BrrMaster", "project_code"),
    "/billing/brb":             (("bill_receive_register",), "brbMaster:BrbMaster", "project_code"),
    "/billing/payment-request": (("payment_request", "payment_request_journal"),
                                 "paymentRequest:PaymentRequestMaster", "project_code"),
    # ---- Logistics ----
    "/logistics/transit-request": (("transit_request",), "transitRequest:TransitRequest", "project_code"),
    "/logistics/bill-register":   (("logistics_bill_register",), "logisticsBill:LogisticsBill", "project_code"),
    # ---- Project management ----
    "/project-mgmt/register/drawing-register":   (("drawing_register",), "drawingRegister:DrawingRegister", "project_code"),
    "/project-mgmt/register/bbs-register":       (("bbs_register",), "bbsRegister:BbsRegister", "project_code"),
    "/project-mgmt/register/hindrance-register": (("hindrance_register",), "hindranceRegister:HindranceRegister", "project_code"),
    "/project-mgmt/register/concrete-registry":  (("concrete_register",), "concrete_registry:ConcreteRegistry", "projectcode"),
    "/project-mgmt/billing":              (("sale_claim_bill", "sale_certified_bill"), "billingMaster:BillingMaster", "project_code"),
    "/project-mgmt/og-sale-order":        (("sale_order",), "ogSaleOrder:OgSaleOrderMaster", "project_code"),
    "/project-mgmt/og-sale-order/amendment": (("sale_order",), "ogSaleOrder:OgSaleOrderAmendment", "project_code"),
    "/project-mgmt/uncertain-allocation": (("uncertified_statement",), "uncertainAllocation:UncertainAllocationMaster", "project_code"),
    "/project-mgmt/contract/budget":      (("budget_master",), "budget:BudgetMaster", "project_code"),
    # ---- Finance ----
    "/finance/sale-bill":            (("sale",), "saleBill:SaleBillMaster", "project_code"),
    "/finance/purchase-bill":        (("purchases",), "purchaseBill:PurchaseBillMaster", "project_code"),
    "/finance/sale-receipt":         (("receipt",), "saleReceipt:SaleReceiptMaster", "project_code"),
    "/finance/sale-receipt-billing": (("receipt",), "saleReceiptBilling:SaleReceiptBillingMaster", "project_code"),
    "/finance/contra-entry":         (("contra",), "contraEntry:ContraEntryMaster", "project_code"),
    "/finance/debit-note":           (("debit_note",), "debitNote:DebitNoteMaster", "project_code"),
    "/finance/credit-note":          (("credit_note",), "creditNote:CreditNoteMaster", "project_code"),
    "/finance/payment-voucher":      (("payment",), "paymentVoucher:PaymentVoucherMaster", "project_code"),
    "/finance/bill-payment":         (("payment",), "billPaymentReceipt:BillPaymentReceiptMaster", "project_code"),
    "/finance/advance-adjustment":   (("payment",), "advanceAdjustment:AdvanceAdjustmentMaster", "project_code"),
    "/finance/journal-entry":        (("journal",), "journalEntry:JournalEntryMaster", "project_code"),
    "/finance/journal-entry/journal-voucher": (("journal", "petty_cash"), "journalVoucher:PettyCashJournalVoucher", "project_code"),
    "/finance/petty-cash/budget":         (("petty_cash",), "pettyCashBudget:PettyCashBudget", "project_code"),
    "/finance/petty-cash/docket-voucher": (("petty_cash",), "pettyCashDocketVoucher:PettyCashDocketVoucher", "project_code"),
    "/finance/accounting/opening-balance": (("accounting_opening_balance",), "accounting:AccountingLedger", "project_code"),
}

# Company-wide setup writes: admin / super_admin only.
ADMIN_ONLY = {
    "/finance/accounting/financial-year",
    "/finance/accounting/historical-posting",
    "/finance/accounting/fix-gst-lines",
}
ADMIN_ROLES = {"admin", "super_admin"}

# Records here may have no project (company-level); those need an admin.
NULLABLE_PROJECT = {"/finance/accounting/opening-balance"}

_SORTED_PREFIXES = sorted(RULES, key=len, reverse=True)
_model_cache = {}


def _model(ref):
    if ref not in _model_cache:
        mod, cls = ref.split(":")
        _model_cache[ref] = getattr(importlib.import_module(f"app.models.{mod}"), cls)
    return _model_cache[ref]


def _match(path):
    for p in _SORTED_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return p
    return None


def _payload_project_code():
    body = request.get_json(silent=True) if request.is_json else None
    for src in (body or {}, request.form, request.args):
        for key in ("projectCode", "project_code"):
            v = src.get(key) if hasattr(src, "get") else None
            if v:
                return str(v).strip()
    return None


def _record_id():
    """First int URL arg, e.g. /edit/<int:indent_id>."""
    for v in (request.view_args or {}).values():
        if isinstance(v, int):
            return v
    return None


def _resolve_project_code(prefix, model_ref, attr):
    rec_id = _record_id()
    if rec_id is not None:
        Model = _model(model_ref)
        rec = Model.query.get(rec_id)
        if rec is None:
            return None, "not_found"
        return getattr(rec, attr, None), None

    # Enquiry is created from an indent and takes its project.
    if prefix == "/resource/enquiry":
        body = request.get_json(silent=True) or {}
        indent_id = body.get("indentId") or request.form.get("indentId")
        if indent_id:
            from app.models.indent_master import IndentMaster
            ind = IndentMaster.query.get(indent_id)
            return (ind.project_code if ind else None), None

    return _payload_project_code(), None


def _user_has_edit(project_code, user_id, page_codes):
    from app.models.project import Project
    from app.modules.setting.permission_service import get_user_permissions
    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return False
    perms = get_user_permissions(project.id, user_id) or {}
    return any(perms.get(f"{pc}.EDIT") for pc in page_codes)


def _has_valid_token():
    """False for a missing/invalid token, so the route's own @login_required
    answers 401. Any other error (e.g. DB down) is raised: never fail open."""
    try:
        verify_jwt_in_request()
        return True
    except (JWTExtendedException, PyJWTError):
        return False


def register_project_guard(app):

    @app.before_request
    def project_permission_guard():
        if request.method not in WRITE_METHODS:
            return None

        if request.path in ADMIN_ONLY:
            if not _has_valid_token():
                return None
            if get_jwt().get("role") not in ADMIN_ROLES:
                return res("Only admin can do this", [], 403)
            return None

        prefix = _match(request.path)
        if not prefix:
            return None

        segments = set(request.path[len(prefix):].strip("/").split("/"))
        if segments & APPROVAL_ACTIONS:
            return None

        if not _has_valid_token():
            return None

        if get_jwt().get("role") == "super_admin":
            return None

        page_codes, model_ref, attr = RULES[prefix]

        project_code, err = _resolve_project_code(prefix, model_ref, attr)
        if err == "not_found":
            return None  # the route returns its own 404
        if not project_code:
            if prefix in NULLABLE_PROJECT:
                if get_jwt().get("role") in ADMIN_ROLES:
                    return None
                return res("Only admin can do this for company-level entries", [], 403)
            return res("projectCode required", [], 400)

        if not _user_has_edit(project_code, int(get_jwt_identity()), page_codes):
            return res(
                f"You do not have edit permission for this page in project {project_code}",
                [], 403,
            )
        return None
