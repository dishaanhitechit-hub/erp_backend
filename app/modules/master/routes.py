from flask import send_from_directory
from flask import make_response
from flask import Blueprint, request
from flask import send_from_directory

from app.middleware.auth_middleware import login_required

from app.middleware.role_middleware import require_super_admin,require_admin

from app.modules.master.service import *

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
@require_admin
def vendor_list():
    return get_all_vendors()


@master_bp.route("/ledger/<int:vendorId>", methods=["GET"])
@login_required
@require_admin
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


# ITEM ROUTES


@master_bp.route("/item/create", methods=["POST"])
@login_required
@require_admin
def item_create():
    # data = request.args.to_dict() if request.args else request.json
    return create_item(request.json)


@master_bp.route("/item/list", methods=["GET"])
@login_required
@require_admin
def item_list():
    return get_all_items()


@master_bp.route("/item/<int:itemId>", methods=["GET"])
@login_required
@require_admin
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
@require_admin
def cc_code_list():
    data = request.args.to_dict() if request.args else {}
    return get_all_cc_codes(data)


@master_bp.route("/cc-code/<int:ccId>", methods=["GET"])
@login_required
@require_admin
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
@require_admin
def group_list():
    return get_all_groups()


@master_bp.route("/group/update/<int:groupId>", methods=["PUT"])
@login_required
@require_admin
def group_update(groupId):
    return update_group(groupId, request.json)



# CATEGORY ROUTES


@master_bp.route("/category/create", methods=["POST"])
@login_required
@require_admin
def category_create():

    return create_category(request.json)


@master_bp.route("/category/list", methods=["GET"])
@login_required
@require_admin
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
@require_admin
def asset_list():
    return get_all_assets()


@master_bp.route("/asset/<int:assetId>", methods=["GET"])
@login_required
@require_admin
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
@require_admin
def unit_list():

    filters = {
        "unitType": request.args.get("unitType"),
        "categoryId": request.args.get("categoryId")
    }

    return get_all_units(filters)

@master_bp.route("/unit/<int:unitId>", methods=["GET"])
@login_required
@require_admin
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

