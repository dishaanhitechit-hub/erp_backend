
from flask import Blueprint, request
import json
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


    data = dict(
        request.form
    )

    items = json.loads(

        data.get(
            "items",
            "[]"
        )
    )

    data["items"] = items

    files = request.files

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
        files=files,
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

    data = dict(request.form)

    items = json.loads(data.get("items", "null"))

    data["items"] = items

    files = request.files

    return update_indent(
        indent_id=indent_id,
        data=data,
        files=files,
        updated_by=g.current_user.get("id") if hasattr(g, "current_user") else None
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

    submitted_by = g.current_user.get("id") if hasattr(g, "current_user") else None

    return submit_indent(
        indent_id=indent_id,
        submitted_by=submitted_by
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

# =========================================================
# APPROVE INDENT
# =========================================================

@indent_bp.route(
    "/approve/<int:indent_id>",
    methods=["POST"]
)
@login_required
def approve(indent_id):
    print(
        g.current_user
    )

    print(
        type(
            g.current_user
        )
    )
    data = request.get_json() or {}

    approved_by = (
        g.current_user.get("id")
        if hasattr(
            g,
            "current_user"
        )
        else None
    )

    return approve_indent(

        indent_id=
        indent_id,

        approved_by=
        approved_by,

        comments=
        data.get(
            "comments"
        )
    )


# =========================================================
# REBACK INDENT
# =========================================================

@indent_bp.route(
    "/reback/<int:indent_id>",
    methods=["POST"]
)
@login_required
def reback(indent_id):

    data = request.get_json() or {}

    reback_by = (
        g.current_user.get("id")
        if hasattr(
            g,
            "current_user"
        )
        else None
    )

    return reback_indent(

        indent_id=
        indent_id,

        reback_by=
        reback_by,

        comments=
        data.get(
            "comments"
        )
    )


# =========================================================
# REJECT INDENT
# =========================================================

@indent_bp.route(
    "/reject/<int:indent_id>",
    methods=["POST"]
)
@login_required
def reject(indent_id):

    data = request.get_json() or {}

    rejected_by = (
        g.current_user.get("id")
        if hasattr(
            g,
            "current_user"
        )
        else None
    )

    return reject_indent(

        indent_id=
        indent_id,

        rejected_by=
        rejected_by,

        comments=
        data.get(
            "comments"
        )
    )


# =========================================================
# INDENT HISTORY
# =========================================================

@indent_bp.route(
    "/history/<int:indent_id>",
    methods=["GET"]
)
@login_required
def history(indent_id):

    return get_indent_history(
        indent_id
    )