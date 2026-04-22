from flask import send_from_directory
from flask import make_response
from flask import Blueprint, request
from .service import create_company, get_company_by_id, update_company,get_my_companies
import os

from app.middleware.auth_middleware import login_required

from app.middleware.role_middleware import require_super_admin

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads/company")
company_bp = Blueprint("company", __name__)

@company_bp.route("/uploads/company/<filename>", methods=["GET"])
def get_company_file(filename):
    response = make_response(send_from_directory(UPLOAD_FOLDER, filename))
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# CREATE
@company_bp.route("/company", methods=["POST"])
@login_required
@require_super_admin
def create():
    return create_company(request)

# GET BY ID
@company_bp.route("/company", methods=["GET"])
@company_bp.route("/company/<int:company_id>", methods=["GET"])
@login_required
@require_super_admin
def get_company(company_id = None):
    return get_company_by_id(company_id, request)

# UPDATE
@company_bp.route("/company/<int:company_id>", methods=["PUT"])
@login_required
@require_super_admin
def update(company_id):
    return update_company(company_id, request)

@company_bp.route("/my-companies", methods=["GET"])
@login_required
@require_super_admin
def get_my_company():
    return get_my_companies()