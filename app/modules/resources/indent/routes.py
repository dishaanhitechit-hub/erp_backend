
from flask import Blueprint, request

from flask import g
from app.middleware.auth_middleware import login_required

from app.middleware.role_middleware import require_super_admin,require_admin
from app.modules.resources.indent.service import *
indent_bp = Blueprint( "indent",__name__)

@indent_bp.route("/items-by-category", methods=["GET"])
@login_required
def items_by_category():

    category_code = request.args.get("categoryCode")

    if not category_code:
        return {
            "msg": "categoryCode is required",
            "data": [],
            "status": 400
        }, 400

    return get_items_by_category(category_code)

@indent_bp.route("/create", methods=["POST"])
@login_required
def create():

    data = request.get_json()

    if not data:
        return {
            "msg": "Invalid payload",
            "data": [],
            "status": 400
        }, 400

    if hasattr(g, "current_user"):
        created_by = g.current_user.get("id")
    else:
        created_by = None

    return create_indent(
        data=data,
        created_by=created_by
    )



# INDENT LIST

#
# GET /resource/indent/list
#
# OPTIONAL FILTERS:
# ?projectCode=
# ?categoryCode=
# ?status=
#


@indent_bp.route("/list", methods=["GET"])
@login_required
def indent_list():

    filters = request.args.to_dict()

    return get_indent_list(filters)



#
# GET /resource/indent/<id>
#


@indent_bp.route("/<int:indent_id>", methods=["GET"])
@login_required
def indent_details(indent_id):

    return get_indent_details(indent_id)

@indent_bp.route(
    "/update/<int:indent_id>",
    methods=["PUT"]
)
@login_required
def update(indent_id):

    return update_indent(
        indent_id=indent_id,
        data=request.get_json(),
        updated_by=None
    )


# =========================================================
# SUBMIT INDENT
# =========================================================

@indent_bp.route(
    "/submit/<int:indent_id>",
    methods=["POST"]
)
@login_required
def submit(indent_id):

    return submit_indent(
        indent_id=indent_id,
        submitted_by=None
    )


# =========================================================
# DELETE INDENT
# =========================================================

@indent_bp.route(
    "/delete/<int:indent_id>",
    methods=["DELETE"]
)
@login_required
def delete(indent_id):

    return delete_indent(indent_id)

