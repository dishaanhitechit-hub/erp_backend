from flask import send_from_directory
from flask import Blueprint, request ,jsonify,abort
from .service import create_company, get_company_by_id, update_company
import os
from app.middleware.auth_middleware import login_required
from app.response import res
from app.middleware.role_middleware import require_super_admin

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads/company")
company_bp = Blueprint("company", __name__)

@company_bp.route("/uploads/company/<filename>", methods=["GET"])
@login_required
@require_super_admin
def get_company_file(filename):
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except FileNotFoundError:
        return abort(404, description="File not found")

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