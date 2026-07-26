from flask import Blueprint, request

from app.middleware.auth_middleware import login_required
from app.middleware.permission_middleware import page_permission
from app.response import res

from app.modules.resources.manpower.service import (
    create_manpower,
    get_all_manpower,
    get_manpower_by_id,
    update_manpower,
    get_labour_categories,
)

manpower_bp = Blueprint("manpower", __name__)

MODULE = "labour_id"


# ── Category list (no special permission needed — used by dropdowns) ──────────

@manpower_bp.route("/categories", methods=["GET"])
@login_required
def labour_categories():
    return get_labour_categories()


# ── Create (requires labour_id.EDIT permission) ───────────────────────────────

@manpower_bp.route("/create", methods=["POST"])
@login_required
@page_permission(MODULE, "EDIT")
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


# ── Update (requires labour_id.EDIT permission + must be creator of record) ───

@manpower_bp.route("/update/<int:worker_id>", methods=["PUT"])
@login_required
@page_permission(MODULE, "EDIT")
def manpower_update(worker_id):
    return update_manpower(worker_id, request)
