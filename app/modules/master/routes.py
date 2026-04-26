from flask import send_from_directory
from flask import make_response
from flask import Blueprint, request


from app.middleware.auth_middleware import login_required

from app.middleware.role_middleware import require_super_admin,require_admin

from app.modules.master.service import *
master_bp = Blueprint('master', __name__)


# ==========================================
# VENDOR ROUTES
# ==========================================

@master_bp.route("/vendor/create", methods=["POST"])
@login_required
@require_admin
def vendor_create():
    return create_vendor(request)


@master_bp.route("/vendor/list", methods=["GET"])
@login_required
@require_admin
def vendor_list():
    return get_all_vendors()


@master_bp.route("/vendor/<int:vendorId>", methods=["GET"])
@login_required
@require_admin
def vendor_detail(vendorId):
    return get_vendor_by_id(vendorId)


@master_bp.route("/vendor/update/<int:vendorId>", methods=["PUT"])
@login_required
@require_admin
def vendor_update(vendorId):
    return update_vendor(vendorId, request)


@master_bp.route("/vendor/delete/<int:vendorId>", methods=["DELETE"])
@login_required
@require_admin
def vendor_delete(vendorId):
    return delete_vendor(vendorId)


# ITEM ROUTES


@master_bp.route("/item/create", methods=["POST"])
@login_required
@require_admin
def item_create():
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
    return get_all_cc_codes()


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
    return get_all_categories()


@master_bp.route("/category/update/<int:categoryId>", methods=["PUT"])
@login_required
@require_admin
def category_update(categoryId):
    return update_category(categoryId, request.json)