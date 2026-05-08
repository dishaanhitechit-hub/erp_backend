import os
from flask import Blueprint, request, g

from app.middleware.auth_middleware import login_required
from app.modules.resources.enquiry.service import (
    get_indent_items_for_enquiry,
    create_enquiry,
    get_enquiry_list,
    get_enquiry_details,
    update_enquiry,
    submit_enquiry,
    delete_enquiry,
    attach_quotation,
)

enquiry_bp = Blueprint("enquiry", __name__)


# =========================================================
# HELPER  — current user id
# =========================================================

def _user_id():
    return (
        g.current_user.get("id")
        if hasattr(g, "current_user") else None
    )


# =========================================================
# GET INDENT ITEMS  (pre-fill enquiry form)
#
# GET /resource/enquiry/indent-items/<indent_id>
# =========================================================

@enquiry_bp.route(
    "/indent-items/<int:indent_id>",
    methods=["GET"]
)
@login_required
def indent_items(indent_id):
    return get_indent_items_for_enquiry(indent_id)


# =========================================================
# CREATE ENQUIRY
#
# POST /resource/enquiry/create
#
# Body:
# {
#   "indentId": 1,
#   "enquiryTo": "Party Name",
#   "address":   "Party Address",
#   "items": [
#     {
#       "indentItemId": 1,
#       "enquiryQty":   20,
#       "location":     "Site A",
#       "note":         ""
#     }
#   ],
#   "terms": [
#     { "header": "Payment", "description": "30 days" }
#   ]
# }
# =========================================================

@enquiry_bp.route("/create", methods=["POST"])
@login_required
def create():

    data = request.get_json()

    if not data:
        return {
            "msg": "Invalid payload",
            "data": [],
            "status": 400
        }, 400

    return create_enquiry(data=data, created_by=_user_id())


# =========================================================
# ENQUIRY LIST
#
# GET /resource/enquiry/list
# Optional: ?projectCode= &categoryCode= &status=
# =========================================================

@enquiry_bp.route("/list", methods=["GET"])
@login_required
def enquiry_list():
    filters = request.args.to_dict()
    return get_enquiry_list(filters)


# =========================================================
# ENQUIRY DETAILS
#
# GET /resource/enquiry/<id>
# =========================================================

@enquiry_bp.route("/<int:enquiry_id>", methods=["GET"])
@login_required
def enquiry_details(enquiry_id):
    return get_enquiry_details(enquiry_id)


# =========================================================
# UPDATE ENQUIRY  (Draft only)
#
# PUT /resource/enquiry/update/<id>
# =========================================================

@enquiry_bp.route(
    "/update/<int:enquiry_id>",
    methods=["PUT"]
)
@login_required
def update(enquiry_id):

    data = request.get_json()

    if not data:
        return {
            "msg": "Invalid payload",
            "data": [],
            "status": 400
        }, 400

    return update_enquiry(
        enquiry_id=enquiry_id,
        data=data,
        updated_by=_user_id()
    )


# =========================================================
# SUBMIT ENQUIRY
#
# POST /resource/enquiry/submit/<id>
# =========================================================

@enquiry_bp.route(
    "/submit/<int:enquiry_id>",
    methods=["POST"]
)
@login_required
def submit(enquiry_id):
    return submit_enquiry(
        enquiry_id=enquiry_id,
        submitted_by=_user_id()
    )


# =========================================================
# DELETE ENQUIRY  (Draft only)
#
# DELETE /resource/enquiry/delete/<id>
# =========================================================

@enquiry_bp.route(
    "/delete/<int:enquiry_id>",
    methods=["DELETE"]
)
@login_required
def delete(enquiry_id):
    return delete_enquiry(enquiry_id)


# =========================================================
# ATTACH QUOTATION  (multipart/form-data)
#
# POST /resource/enquiry/attach-quotation/<id>
# form-data key: "file"
# =========================================================

@enquiry_bp.route(
    "/attach-quotation/<int:enquiryId>",
    methods=["POST"]
)
@login_required
def attach_quotation_route(enquiryId):

    return attach_quotation(enquiryId,request)