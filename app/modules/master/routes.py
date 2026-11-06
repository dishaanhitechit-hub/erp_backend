from flask import send_from_directory
from flask import make_response
from flask import Blueprint, request, jsonify
from flask import send_from_directory

from flask_jwt_extended import get_jwt

from app.middleware.auth_middleware import login_required
from app.middleware.role_middleware import require_super_admin, require_admin
from app.response import res

from app.modules.master.service import *
from app.modules.master.supplier_service import (
    create_supplier, get_all_suppliers, get_supplier_by_id,
    update_supplier, delete_supplier, link_ledger, unlink_ledger,
    get_nature_of_service, bulk_assign_projects, bulk_remove_projects,
)

from app.modules.master.sub_group_service import (
    create_sub_group, update_sub_group, get_all_sub_groups, get_sub_group_by_id,
    delete_sub_group, check_sub_group_code, suggest_sub_group_code,
)

master_bp = Blueprint('master', __name__)
UPLOAD_FOLDER = "/uploads/vendor"

# ==========================================
# VENDOR ROUTES
# ==========================================

@master_bp.route("/ledger/create", methods=["POST"])
@login_required
@require_admin
def vendor_create():
    return create_vendor(request)


@master_bp.route("/ledger/list", methods=["GET"])
@login_required
# @require_admin
def vendor_list():
    from flask import request as req
    ledger_type = req.args.get("type")  # "debtor" | "creditor" | None (all)
    return get_all_vendors(ledger_type=ledger_type)


@master_bp.route("/ledger/<int:vendorId>", methods=["GET"])
@login_required
# @require_admin
def vendor_detail(vendorId):
    return get_vendor_by_id(vendorId)


@master_bp.route("/ledger/update/<int:vendorId>", methods=["PUT"])
@login_required
@require_admin
def vendor_update(vendorId):
    return update_vendor(vendorId, request)


@master_bp.route("/ledger/delete/<int:vendorId>", methods=["DELETE"])
@login_required
@require_admin
def vendor_delete(vendorId):
    return delete_vendor(vendorId)



# ==========================================
# SUPPLIER ROUTES
# ==========================================

@master_bp.route("/supplier/create", methods=["POST"])
@login_required
def supplier_create():
    return create_supplier(request)


@master_bp.route("/supplier/list", methods=["GET"])
@login_required
def supplier_list():
    return get_all_suppliers()


@master_bp.route("/supplier/<int:supplierId>", methods=["GET"])
@login_required
def supplier_detail(supplierId):
    return get_supplier_by_id(supplierId)


@master_bp.route("/supplier/update/<int:supplierId>", methods=["PUT"])
@login_required
def supplier_update(supplierId):
    return update_supplier(supplierId, request)


@master_bp.route("/supplier/delete/<int:supplierId>", methods=["DELETE"])
@login_required
def supplier_delete(supplierId):
    return delete_supplier(supplierId)


@master_bp.route("/supplier/<int:supplierId>/link-ledger", methods=["POST"])
@login_required
def supplier_link_ledger(supplierId):
    return link_ledger(supplierId, request)


@master_bp.route("/supplier/<int:supplierId>/unlink-ledger/<int:ledgerId>", methods=["DELETE"])
@login_required
def supplier_unlink_ledger(supplierId, ledgerId):
    return unlink_ledger(supplierId, ledgerId)


@master_bp.route("/supplier/bulk-assign-projects", methods=["POST"])
@login_required
@require_admin
def supplier_bulk_assign_projects():
    return bulk_assign_projects(request)


@master_bp.route("/supplier/bulk-remove-projects", methods=["DELETE"])
@login_required
@require_admin
def supplier_bulk_remove_projects():
    return bulk_remove_projects(request)


@master_bp.route("/supplier/nature-of-service", methods=["GET"])
@login_required
def supplier_nature_of_service():
    return get_nature_of_service()


# ITEM ROUTES


@master_bp.route("/item/create", methods=["POST"])
@login_required
@require_admin
def item_create():
    # data = request.args.to_dict() if request.args else request.json
    return create_item(request.json)


@master_bp.route("/item/list", methods=["GET"])
@login_required
# @require_admin
def item_list():
    return get_all_items()


@master_bp.route("/item/<int:itemId>", methods=["GET"])
@login_required
# @require_admin
def item_detail(itemId):
    return get_item_by_id(itemId)


@master_bp.route("/item/update/<int:itemId>", methods=["PUT"])
@login_required
@require_admin
def item_update(itemId):
    # data = request.args.to_dict() if request.args else request.json
    return update_item(itemId, request.json)


@master_bp.route("/item/delete/<int:itemId>", methods=["DELETE"])
@login_required
@require_admin
def item_delete(itemId):
    return delete_item(itemId)


# CC CODE ROUTES


@master_bp.route("/cc-code/create", methods=["POST"])
@login_required
@require_admin
def cc_code_create():
    createdBy = None
    return create_cc_code(request.json, createdBy)


@master_bp.route("/cc-code/list", methods=["GET"])
@login_required
# @require_admin
def cc_code_list():
    data = request.args.to_dict() if request.args else {}
    return get_all_cc_codes(data)


@master_bp.route("/cc-code/<int:ccId>", methods=["GET"])
@login_required
# @require_admin
def cc_code_detail(ccId):
    return get_cc_code_by_id(ccId)


@master_bp.route("/cc-code/update/<int:ccId>", methods=["PUT"])
@login_required
@require_admin
def cc_code_update(ccId):
    return update_cc_code(ccId, request.json)


@master_bp.route("/cc-code/delete/<int:ccId>", methods=["DELETE"])
@login_required
@require_admin
def cc_code_delete(ccId):
    return delete_cc_code(ccId)

@master_bp.route("/group/create", methods=["POST"])
@login_required
@require_admin
def group_create():

    return create_group(request.json)


@master_bp.route("/group/list", methods=["GET"])
@login_required
# @require_admin
def group_list():
    return get_all_groups()


@master_bp.route("/group/update/<int:groupId>", methods=["PUT"])
@login_required
@require_admin
def group_update(groupId):
    return update_group(groupId, request.json)



# SUB GROUP ROUTES


@master_bp.route("/sub-group/create", methods=["POST"])
@login_required
@require_admin
def sub_group_create():
    return create_sub_group(request.json or {})


@master_bp.route("/sub-group/list", methods=["GET"])
@login_required
def sub_group_list():
    return get_all_sub_groups(request.args.to_dict() if request.args else {})


@master_bp.route("/sub-group/check-code", methods=["GET"])
@login_required
def sub_group_check_code():
    # live check while typing: ?code=&excludeId=
    return check_sub_group_code(request.args.to_dict())


@master_bp.route("/sub-group/suggest-code", methods=["GET"])
@login_required
def sub_group_suggest_code():
    # preview auto code: ?name=&parentId=
    return suggest_sub_group_code(request.args.to_dict())


@master_bp.route("/sub-group/<int:subGroupId>", methods=["GET"])
@login_required
def sub_group_detail(subGroupId):
    return get_sub_group_by_id(subGroupId)


@master_bp.route("/sub-group/update/<int:subGroupId>", methods=["PUT"])
@login_required
@require_admin
def sub_group_update(subGroupId):
    return update_sub_group(subGroupId, request.json or {})


@master_bp.route("/sub-group/delete/<int:subGroupId>", methods=["DELETE"])
@login_required
@require_admin
def sub_group_delete(subGroupId):
    return delete_sub_group(subGroupId)


# CATEGORY ROUTES


@master_bp.route("/category/create", methods=["POST"])
@login_required
@require_admin
def category_create():

    return create_category(request.json)


@master_bp.route("/category/list", methods=["GET"])
@login_required
# @require_admin
def category_list():
    data = request.args.to_dict() if request.args else {}
    return get_all_categories(data)


@master_bp.route("/category/update/<int:categoryId>", methods=["PUT"])
@login_required
@require_admin
def category_update(categoryId):
    return update_category(categoryId, request.json)

# ASSET ROUTE

@master_bp.route("/asset/create", methods=["POST"])
@login_required
@require_admin
def asset_create():
    # data = request.args.to_dict() if request.args else request.json
    return create_asset(request.json)


@master_bp.route("/asset/list", methods=["GET"])
@login_required
# @require_admin
def asset_list():
    return get_all_assets()


@master_bp.route("/asset/<int:assetId>", methods=["GET"])
@login_required
# @require_admin
def asset_detail(assetId):
    return get_asset_by_id(assetId)


@master_bp.route("/asset/update/<int:assetId>", methods=["PUT"])
@login_required
@require_admin
def asset_update(assetId):
    # data = request.args.to_dict() if request.args else request.json
    return update_asset(assetId, request.json)


@master_bp.route("/asset/delete/<int:assetId>", methods=["DELETE"])
@login_required
@require_admin
def asset_delete(assetId):
    return delete_asset(assetId)

@master_bp.route("/unit/create", methods=["POST"])
@login_required
@require_admin
def unit_create():
    return create_unit(request.json)


@master_bp.route("/unit/list", methods=["GET"])
@login_required
# @require_admin
def unit_list():

    filters = {
        "unitType": request.args.get("unitType"),
        "categoryId": request.args.get("categoryId")
    }

    return get_all_units(filters)

@master_bp.route("/unit/<int:unitId>", methods=["GET"])
@login_required
# @require_admin
def unit_detail(unitId):
    return get_unit_by_id(unitId)


@master_bp.route("/unit/update/<int:unitId>", methods=["PUT"])
@login_required
@require_admin
def unit_update(unitId):
    return update_unit(unitId, request.json)


@master_bp.route("/unit/delete/<int:unitId>", methods=["DELETE"])
@login_required
@require_admin
def unit_delete(unitId):
    return delete_unit(unitId)

@master_bp.route("/term/create", methods=["POST"])
@login_required
@require_admin
def term_create():
    return create_term(request.json)

@master_bp.route("/term/list", methods=["GET"])
@login_required
# @require_admin
def term_list():
    return get_all_terms()

@master_bp.route("/term/update/<int:termId>", methods=["PUT"])
@login_required
@require_admin
def term_update(termId):
    return term_edit(termId, request.json)

@master_bp.route("/term/<int:termId>", methods=["GET"])
@login_required
# @require_admin
def term_detail(termId):
    return get_term_by_id(termId)


@master_bp.route("/term/delete/<int:termId>", methods=["DELETE"])
@login_required
@require_admin
def term_delete(termId):
    return delete_term(termId)


# ==========================================
# BANK & CASH
# ==========================================

_PAGE_BANK = "bank_cash"


def _can_view_bank():
    perms = {k.lower(): v for k, v in get_jwt().get("permissions", {}).items()}
    return perms.get(f"{_PAGE_BANK}.view") or perms.get(f"{_PAGE_BANK}.edit")


def _can_edit_bank():
    claims = get_jwt()
    if claims.get("role") in ("admin", "super_admin"):
        return True
    perms = {k.lower(): v for k, v in claims.get("permissions", {}).items()}
    return perms.get(f"{_PAGE_BANK}.edit")


def _no_access():
    return jsonify({"message": "Access denied", "data": [], "status": 403}), 403


@master_bp.route("/bank-cash/create", methods=["POST"])
@login_required
def bank_cash_create():
    if not _can_edit_bank():
        return _no_access()
    return create_bank_cash(request.json)


@master_bp.route("/bank-cash/list", methods=["GET"])
@login_required
def bank_cash_list():
    # if not _can_view_bank():
    #     return _no_access()
    type_filter = request.args.get("type")
    project_id  = request.args.get("projectId", type=int)
    return get_all_bank_cash(type_filter=type_filter, project_id=project_id)


@master_bp.route("/bank-cash/<int:recordId>", methods=["GET"])
@login_required
def bank_cash_detail(recordId):
    # if not _can_view_bank():
    #     return _no_access()
    return get_bank_cash_by_id(recordId)


@master_bp.route("/bank-cash/update/<int:recordId>", methods=["PUT"])
@login_required
def bank_cash_update(recordId):
    if not _can_edit_bank():
        return _no_access()
    return update_bank_cash(recordId, request.json)


@master_bp.route("/bank-cash/delete/<int:recordId>", methods=["DELETE"])
@login_required
def bank_cash_delete(recordId):
    if not _can_edit_bank():
        return _no_access()
    return delete_bank_cash(recordId)


@master_bp.route("/bank-cash/migrate", methods=["POST"])
@login_required
def bank_cash_migrate():
    if not _can_edit_bank():
        return _no_access()
    data = request.json or {}
    return migrate_bank_cash_to_projects(
        data.get("bankCashIds", []),
        data.get("projectIds", [])
    )


@master_bp.route("/bank-cash/<int:recordId>/link-project", methods=["POST"])
@login_required
def bank_cash_link_project(recordId):
    if not _can_edit_bank():
        return _no_access()
    data = request.json or {}
    return link_bank_cash_project(recordId, data.get("projectId"))


@master_bp.route("/bank-cash/<int:recordId>/unlink-project", methods=["POST"])
@login_required
def bank_cash_unlink_project(recordId):
    if not _can_edit_bank():
        return _no_access()
    data = request.json or {}
    return unlink_bank_cash_project(recordId, data.get("projectId"))


# ==========================================
# VENDOR DROPDOWN
# ==========================================

@master_bp.route("/ledger/dropdown", methods=["GET"])
@login_required
def vendor_dropdown():
    from flask import request as _req
    ledger_type  = _req.args.get("type")
    project_code = _req.args.get("projectCode")
    return get_vendor_dropdown(ledger_type=ledger_type, project_code=project_code)

