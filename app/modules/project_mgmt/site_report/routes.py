"""Daily Progress Report API — mounted at /project-mgmt/dpr."""

import json

from flask import Blueprint, g, request

from app.middleware.auth_middleware import login_required
from app.response import res

from . import service as svc

dpr_bp = Blueprint("daily_progress_report", __name__)


def _user():
    return g.current_user


# ── Photos ──────────────────────────────────────────────────────────

@dpr_bp.route("/photos", methods=["POST"])
@login_required
def api_upload_photos():
    """multipart: projectCode, photos (files), meta (JSON list, one object per photo)."""
    try:
        metas = json.loads(request.form.get("meta") or "[]")
        if not isinstance(metas, list):
            metas = []
    except ValueError:
        return res("meta must be a JSON list", [], 400)
    files = request.files.getlist("photos")
    return svc.upload_photos(request.form.get("projectCode"), files, metas, _user())


@dpr_bp.route("/photos", methods=["GET"])
@login_required
def api_list_photos():
    return svc.list_photos(request.args.get("projectCode"), svc._parse_day(request.args.get("date")), _user())


@dpr_bp.route("/photos/<int:photo_id>", methods=["PUT"])
@login_required
def api_edit_photo(photo_id):
    return svc.edit_photo(photo_id, request.get_json(silent=True) or {}, _user())


@dpr_bp.route("/photos/<int:photo_id>", methods=["DELETE"])
@login_required
def api_delete_photo(photo_id):
    return svc.delete_photo(photo_id, _user())


@dpr_bp.route("/photos/<int:photo_id>/reanalyse", methods=["POST"])
@login_required
def api_reanalyse_photo(photo_id):
    return svc.reanalyse_photo(photo_id, _user())


# ── Days & reports ─────────────────────────────────────────────────

@dpr_bp.route("/list", methods=["GET"])
@login_required
def api_list_days():
    return svc.list_days(request.args.get("projectCode"), _user())


@dpr_bp.route("/day", methods=["GET"])
@login_required
def api_get_day():
    return svc.get_day(request.args.get("projectCode"), svc._parse_day(request.args.get("date")), _user())


@dpr_bp.route("/details/<int:report_id>", methods=["GET"])
@login_required
def api_details(report_id):
    return svc.get_details(report_id, _user())


@dpr_bp.route("/generate", methods=["POST"])
@login_required
def api_generate():
    data = request.get_json(silent=True) or {}
    return svc.generate_report(data.get("projectCode"), svc._parse_day(data.get("date")), _user())


@dpr_bp.route("/edit/<int:report_id>", methods=["PUT"])
@login_required
def api_edit(report_id):
    return svc.edit_report(report_id, request.get_json(silent=True) or {}, _user())


@dpr_bp.route("/submit/<int:report_id>", methods=["POST"])
@login_required
def api_submit(report_id):
    return svc.submit_report(report_id, _user()["id"])


@dpr_bp.route("/approve/<int:report_id>", methods=["POST"])
@login_required
def api_approve(report_id):
    data = request.get_json(silent=True) or {}
    return svc.approve_report(report_id, _user()["id"], data.get("comments"))


@dpr_bp.route("/reback/<int:report_id>", methods=["POST"])
@login_required
def api_reback(report_id):
    data = request.get_json(silent=True) or {}
    return svc.reback_report(report_id, _user()["id"], data.get("comments"))


@dpr_bp.route("/reject/<int:report_id>", methods=["POST"])
@login_required
def api_reject(report_id):
    data = request.get_json(silent=True) or {}
    return svc.reject_report(report_id, _user()["id"], data.get("comments"))


@dpr_bp.route("/history/<int:report_id>", methods=["GET"])
@login_required
def api_history(report_id):
    return svc.history(report_id)


@dpr_bp.route("/my-approval-status/<int:report_id>", methods=["GET"])
@login_required
def api_my_status(report_id):
    return svc.my_approval_status(report_id, _user()["id"])


@dpr_bp.route("/uuid/<string:report_uuid>", methods=["GET"])
def api_by_uuid(report_uuid):
    """Public (no login) — for the print page and shared PDF links."""
    return svc.by_uuid(report_uuid)
