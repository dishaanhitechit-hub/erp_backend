from flask import Blueprint, request

from app.middleware.auth_middleware import login_required

from app.modules.resources.manpower.service import (
    create_manpower,
    get_all_manpower,
    get_manpower_by_id,
    update_manpower,
    get_labour_categories,
    get_manpower_by_supplier,
)

manpower_bp = Blueprint("manpower", __name__)


# ── Category list ─────────────────────────────────────────────────────────────

@manpower_bp.route("/categories", methods=["GET"])
@login_required
def labour_categories():
    return get_labour_categories()


# ── Create (is_creator check done in service via ApprovalPath) ────────────────

@manpower_bp.route("/create", methods=["POST"])
@login_required
def manpower_create():
    return create_manpower(request)


# ── List ──────────────────────────────────────────────────────────────────────

@manpower_bp.route("/list", methods=["GET"])
@login_required
def manpower_list():
    return get_all_manpower()


# ── Detail ────────────────────────────────────────────────────────────────────

@manpower_bp.route("/<int:worker_id>", methods=["GET"])
@login_required
def manpower_detail(worker_id):
    return get_manpower_by_id(worker_id)


# ── Workers by supplier ───────────────────────────────────────────────────────

@manpower_bp.route("/by-supplier/<int:supplier_id>", methods=["GET"])
@login_required
def manpower_by_supplier(supplier_id):
    return get_manpower_by_supplier(supplier_id)


# ── Update (is_creator check done in service via ApprovalPath) ───────────────

@manpower_bp.route("/update/<int:worker_id>", methods=["PUT"])
@login_required
def manpower_update(worker_id):
    return update_manpower(worker_id, request)
