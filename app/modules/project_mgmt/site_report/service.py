"""Daily Progress Report (DPR) — site photos → AI → daily report → approval.

Module code for permissions and the approval workflow: "daily_progress_report".
"""

import logging
import os
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from flask import current_app
from sqlalchemy import text

from app.extensions import db
from app.models.project import Project
from app.models.siteReport import DailyProgressReport, SitePhoto
from app.models.user import User
from app.response import res
from app.modules.work_flow import (
    create_history,
    get_approval_steps,
    get_first_approver,
    get_gap_level,
    get_history,
    get_my_approval_status,
    get_next_approver,
    is_creator,
    is_current_approver,
)

from . import ai, photos as ph

logger = logging.getLogger(__name__)

MODULE_CODE = "daily_progress_report"
EDITABLE = ("Draft", "Reback")
ADMIN_ROLES = ("admin", "super_admin")

# Photos are read by the AI in the background, a few at a time.
_executor = ThreadPoolExecutor(max_workers=int(os.getenv("DPR_AI_WORKERS") or 2), thread_name_prefix="dpr-ai")


# ══════════════════════════════════════════════════════════════════
# Access
# ══════════════════════════════════════════════════════════════════

def _project(project_code):
    return Project.query.filter_by(project_code=project_code).first() if project_code else None


def _perms(project, user_id):
    from app.modules.setting.permission_service import get_user_permissions

    try:
        return get_user_permissions(project.id, int(user_id)) or {}
    except Exception:
        db.session.rollback()
        return {}


def can_add(project, user):
    """Upload photos / write the report: DPR edit permission, DPR creator, or admin."""
    if not project:
        return False
    if (user.get("role") or "") in ADMIN_ROLES:
        return True
    if is_creator(project.project_code, MODULE_CODE, user["id"]):
        return True
    return bool(_perms(project, user["id"]).get(f"{MODULE_CODE}.EDIT"))


def can_view(project, user):
    if can_add(project, user):
        return True
    p = _perms(project, user["id"])
    return bool(p.get(f"{MODULE_CODE}.VIEW") or p.get(f"{MODULE_CODE}.APPROVER"))


def _recipients(project_code):
    """Users who should hear about this project's DPR: its creators and approvers."""
    from app.alias_helper import get_approval_module
    from app.models.approval_path import ApprovalPath

    rows = ApprovalPath.query.filter_by(
        project_code=project_code, module_code=get_approval_module(MODULE_CODE)
    ).all()
    return sorted({r.user_id for r in rows if r.user_id})


def _notify(user_ids, title, body, data):
    if not user_ids:
        return
    try:
        from app.modules.communication.chatting.notification_service import push_to_many

        push_to_many(user_ids, "dpr", title, body, data)
    except Exception:
        logger.exception("DPR notification failed")
        db.session.rollback()


# ══════════════════════════════════════════════════════════════════
# Serialising
# ══════════════════════════════════════════════════════════════════

def _iso(d):
    return d.isoformat() if d else None


def photo_dict(p: SitePhoto):
    return {
        "id": p.id,
        "uuid": p.photo_uuid,
        "projectCode": p.project_code,
        "reportDate": _iso(p.report_date),
        "takenAt": p.taken_at.strftime("%Y-%m-%d %H:%M:%S") if p.taken_at else None,
        "uploadedAt": p.uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if p.uploaded_at else None,
        "source": p.source,
        "timeSource": p.time_source,
        "timeVerified": bool(p.time_verified),
        "latitude": p.latitude,
        "longitude": p.longitude,
        "accuracyM": p.accuracy_m,
        "distanceM": round(p.distance_m) if p.distance_m is not None else None,
        "onSite": p.on_site,
        "isMockLocation": bool(p.is_mock_location),
        "subLocation": p.sub_location,
        "caption": p.caption,
        "fileUrl": p.file_url,
        "thumbUrl": p.thumb_url,
        "width": p.width,
        "height": p.height,
        "aiStatus": p.ai_status,
        "ai": p.ai_result,
        "aiError": p.ai_error if p.ai_status == "failed" else None,
        "uploadedBy": p.uploader.username if p.uploader else None,
        "uploadedById": p.uploaded_by,
    }


def report_dict(r: DailyProgressReport, include_content=True):
    d = {
        "id": r.id,
        "dprNo": r.dpr_no,
        "uuid": r.dpr_uuid,
        "projectCode": r.project_code,
        "projectName": r.project.project_name if r.project else None,
        "reportDate": _iso(r.report_date),
        "summary": r.summary,
        "weather": r.weather,
        "manpowerTotal": r.manpower_total,
        "photoCount": r.photo_count,
        "highlightPhotoIds": r.highlight_photo_ids or [],
        "generatedAt": r.generated_at.strftime("%Y-%m-%d %H:%M:%S") if r.generated_at else None,
        "generatedBy": r.generated_by,
        "aiModel": r.ai_model,
        "edited": bool(r.edited),
        "remarks": r.remarks,
        "workflowStatus": r.workflow_status,
        "currentLevel": r.current_level,
        "locked": bool(r.locked),
        "createdBy": r.creator.username if r.creator else None,
        "approvedBy": r.approver.username if r.approver else None,
        "finalApprovedAt": r.final_approved_at.strftime("%Y-%m-%d %H:%M:%S") if r.final_approved_at else None,
    }
    if include_content:
        d["content"] = r.content or {}
    return d


# ══════════════════════════════════════════════════════════════════
# Photos
# ══════════════════════════════════════════════════════════════════

def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def upload_photos(project_code, files, metas, user):
    """Save photos. `metas[i]` (optional) belongs to `files[i]`:
    takenAt (ISO with offset), latitude, longitude, accuracy, isMocked,
    subLocation, caption. source is 'camera' only for the in-app camera.
    """
    project = _project(project_code)
    if not project:
        return res("Project not found", [], 404)
    if not can_add(project, user):
        return res("You can't add site photos in this project", [], 403)
    if not files:
        return res("No photos sent", [], 400)
    if len(files) > 30:
        return res("Up to 30 photos at a time", [], 400)

    now = ph.now_ist()
    saved, skipped = [], []
    for i, f in enumerate(files):
        meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
        name = getattr(f, "filename", None) or f"photo {i + 1}"
        try:
            prepared = ph.prepare(f.read())
        except ph.PhotoError as e:
            skipped.append({"file": name, "reason": str(e)})
            continue

        dup = SitePhoto.query.filter_by(project_code=project_code, sha256=prepared["sha256"]).first()
        if dup and dup.status == "Active":
            skipped.append({"file": name, "reason": "Already uploaded", "photoId": dup.id})
            continue

        source = "camera" if meta.get("source") == "camera" else "upload"

        # When was it taken?
        client_time = ph.parse_client_time(meta.get("takenAt"))
        if source == "camera" and client_time:
            taken_at, time_source = client_time, "device"
            # Camera photos may arrive late (offline queue) but never from the future or weeks ago.
            time_verified = (now - timedelta(days=7)) <= client_time <= (now + timedelta(minutes=10))
        elif prepared["exif_taken_at"]:
            taken_at, time_source, time_verified = prepared["exif_taken_at"], "exif", False
        else:
            taken_at, time_source, time_verified = now, "upload", False
        if taken_at > now + timedelta(minutes=10):
            taken_at, time_source, time_verified = now, "upload", False

        # Where?
        lat, lng = _num(meta.get("latitude")), _num(meta.get("longitude"))
        if lat is None or lng is None:
            lat, lng = prepared["exif_lat"], prepared["exif_lng"]
        dist = on_site = None
        if lat is not None and lng is not None and project.site_latitude is not None and project.site_longitude is not None:
            dist = ph.distance_m(lat, lng, project.site_latitude, project.site_longitude)
            on_site = dist <= (project.site_radius_m or 500)

        photo_uuid = str(_uuid.uuid4())
        report_date = taken_at.date()
        try:
            file_url, thumb_url = ph.store(project_code, report_date, photo_uuid, prepared["jpeg"], prepared["thumb"])
        except ph.PhotoError as e:
            return res(str(e), [], 500)

        p = SitePhoto(
            photo_uuid=photo_uuid,
            project_code=project_code,
            report_date=report_date,
            taken_at=taken_at,
            uploaded_at=datetime.utcnow(),
            source=source,
            time_source=time_source,
            time_verified=time_verified,
            latitude=lat,
            longitude=lng,
            accuracy_m=_num(meta.get("accuracy")),
            distance_m=dist,
            on_site=on_site,
            is_mock_location=_truthy(meta.get("isMocked")),
            sub_location=(meta.get("subLocation") or "").strip()[:200] or None,
            caption=(meta.get("caption") or "").strip()[:500] or None,
            file_url=file_url,
            thumb_url=thumb_url,
            width=prepared["width"],
            height=prepared["height"],
            sha256=prepared["sha256"],
            ai_status="pending",
            uploaded_by=user["id"],
        )
        if dup:  # same photo was deleted before — reuse the row's unique hash slot
            db.session.delete(dup)
            db.session.flush()
        db.session.add(p)
        db.session.flush()
        saved.append(p)

    db.session.commit()
    for p in saved:
        queue_photo(p.id)
    return res(
        f"{len(saved)} photo(s) saved" + (f", {len(skipped)} skipped" if skipped else ""),
        {"photos": [photo_dict(p) for p in saved], "skipped": skipped},
        201 if saved else 400,
    )


def list_photos(project_code, day, user):
    project = _project(project_code)
    if not project:
        return res("Project not found", [], 404)
    if not can_view(project, user):
        return res("Access denied", [], 403)
    q = SitePhoto.query.filter_by(project_code=project_code, status="Active")
    if day:
        q = q.filter(SitePhoto.report_date == day)
    rows = q.order_by(SitePhoto.taken_at.asc()).all()
    return res("Photos", [photo_dict(p) for p in rows], 200)


def _report_locked(project_code, day):
    r = DailyProgressReport.query.filter_by(project_code=project_code, report_date=day).first()
    return r is not None and r.workflow_status not in EDITABLE + ("Rejected",)


def edit_photo(photo_id, data, user):
    p = SitePhoto.query.get(photo_id)
    if not p or p.status != "Active":
        return res("Photo not found", [], 404)
    if not can_add(_project(p.project_code), user):
        return res("Access denied", [], 403)
    if _report_locked(p.project_code, p.report_date):
        return res("The report for this day is already submitted", [], 400)
    changed = False
    for key, col, size in (("caption", "caption", 500), ("subLocation", "sub_location", 200)):
        if key in data:
            setattr(p, col, (data.get(key) or "").strip()[:size] or None)
            changed = True
    if changed and data.get("reanalyse", True) and p.ai_status in ("done", "failed", "skipped"):
        p.ai_status = "pending"
    db.session.commit()
    if p.ai_status == "pending":
        queue_photo(p.id)
    return res("Photo updated", photo_dict(p), 200)


def delete_photo(photo_id, user):
    p = SitePhoto.query.get(photo_id)
    if not p or p.status != "Active":
        return res("Photo not found", [], 404)
    project = _project(p.project_code)
    if p.uploaded_by != user["id"] and (user.get("role") or "") not in ADMIN_ROLES and not is_creator(p.project_code, MODULE_CODE, user["id"]):
        return res("Only the person who took the photo can delete it", [], 403)
    if not can_add(project, user):
        return res("Access denied", [], 403)
    if _report_locked(p.project_code, p.report_date):
        return res("The report for this day is already submitted", [], 400)
    p.status = "Deleted"
    db.session.commit()
    ph.remove_stored(p.file_url, p.thumb_url)
    return res("Photo deleted", {"id": p.id}, 200)


def reanalyse_photo(photo_id, user):
    p = SitePhoto.query.get(photo_id)
    if not p or p.status != "Active":
        return res("Photo not found", [], 404)
    if not can_add(_project(p.project_code), user):
        return res("Access denied", [], 403)
    p.ai_status, p.ai_error = "pending", None
    db.session.commit()
    queue_photo(p.id)
    return res("Photo queued for AI", photo_dict(p), 200)


# ── AI reading of photos (background) ─────────────────────────────

def queue_photo(photo_id):
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        return  # the sweeper picks it up
    _executor.submit(_process_in_app, app, photo_id)


def _process_in_app(app, photo_id):
    with app.app_context():
        try:
            process_photo(photo_id)
        except Exception:
            logger.exception("DPR photo %s: AI step crashed", photo_id)
            db.session.rollback()
        finally:
            db.session.remove()


def _claim(photo_id):
    """Mark pending → working atomically, so two workers never read the same photo."""
    row = db.session.execute(
        text(
            "UPDATE site_photos SET ai_status = 'working', ai_at = :now "
            "WHERE id = :id AND ai_status = 'pending' AND status = 'Active' RETURNING id"
        ),
        {"id": photo_id, "now": datetime.utcnow()},
    ).first()
    db.session.commit()
    return row is not None


def process_photo(photo_id):
    if not _claim(photo_id):
        return
    p = SitePhoto.query.get(photo_id)
    jpeg = ph.read_stored(p.file_url)
    if jpeg is None:
        p.ai_status, p.ai_error = "failed", "Photo file not found on the server"
        db.session.commit()
        return
    try:
        result = ai.read_photo(jpeg, {
            "caption": p.caption,
            "sub_location": p.sub_location,
            "taken_at": p.taken_at.strftime("%d %b %Y %H:%M") if p.taken_at else None,
        })
    except ai.AiUnavailable as e:
        p.ai_status, p.ai_error = "skipped", str(e)
        db.session.commit()
        return
    except ai.AiFailed as e:
        # Busy/network errors go back to the queue for the sweeper; others stay failed.
        retry = "rate limit" in str(e) or "reach the AI" in str(e) or "AI error 5" in str(e)
        p.ai_status, p.ai_error = ("pending" if retry else "failed"), str(e)
        db.session.commit()
        return

    p.ai_status, p.ai_result, p.ai_error = "done", result, None
    p.ai_at, p.ai_model = datetime.utcnow(), ai.vision_model()
    db.session.commit()
    _maybe_safety_alert(p)


def _maybe_safety_alert(p: SitePhoto):
    """Tell the project's DPR people straight away about a high-severity hazard."""
    if p.safety_alert_sent:
        return
    high = [s for s in (p.ai_result or {}).get("safety_issues", []) if s.get("severity") == "high"]
    if not high:
        return
    p.safety_alert_sent = True
    db.session.commit()
    project = _project(p.project_code)
    where = f" at {p.sub_location}" if p.sub_location else ""
    _notify(
        _recipients(p.project_code),
        f"⚠ Safety issue — {project.project_name if project else p.project_code}",
        f"{high[0]['issue']}{where} ({p.taken_at.strftime('%d %b %H:%M') if p.taken_at else ''})",
        {"module": MODULE_CODE, "projectCode": p.project_code, "date": _iso(p.report_date), "photoId": p.id},
    )


def sweep_pending():
    """Scheduler: re-queue photos still waiting (server restart, rate limits, stuck workers)."""
    stale = datetime.utcnow() - timedelta(minutes=15)
    db.session.execute(
        text("UPDATE site_photos SET ai_status = 'pending' WHERE ai_status = 'working' AND ai_at < :t"),
        {"t": stale},
    )
    db.session.commit()
    ids = [r[0] for r in db.session.execute(
        text("SELECT id FROM site_photos WHERE ai_status = 'pending' AND status = 'Active' ORDER BY id LIMIT 50")
    ).fetchall()]
    for pid in ids:
        try:
            process_photo(pid)
        except Exception:
            logger.exception("DPR sweep: photo %s failed", pid)
            db.session.rollback()
    return len(ids)


# ══════════════════════════════════════════════════════════════════
# The day's site records (what the report is written from)
# ══════════════════════════════════════════════════════════════════

def _rows(sql, params):
    try:
        return [dict(r._mapping) for r in db.session.execute(text(sql), params).fetchall()]
    except Exception:
        logger.exception("DPR day data query failed")
        db.session.rollback()
        return []


def day_records(project_code, day):
    p = {"pc": project_code, "dt": day}
    labour = _rows(
        """SELECT COALESCE(NULLIF(TRIM(di.category), ''), 'Other') AS category, COUNT(*) AS count
           FROM dlr_items di JOIN dlr_master d ON d.id = di.dlr_id
           WHERE d.project_code = :pc AND d.dlr_date = :dt
             AND COALESCE(d.workflow_status, '') <> 'Rejected'
           GROUP BY 1 ORDER BY 2 DESC""", p)
    concrete = _rows(
        """SELECT project_sub_location AS location, segment, grade_concrete AS grade,
                  concrete_volume AS volume, pouring_start_date::text AS start, pouring_end_date::text AS finish
           FROM concrete_registry
           WHERE projectcode = :pc AND pouring_date = :dt
             AND COALESCE(status, 'Active') NOT IN ('Inactive', 'Deleted')""", p)
    materials = _rows(
        """SELECT COALESCE(i.item_name, gi.item_code) AS item, gi.unit,
                  gi.current_received_qty AS quantity, g.grn_no
           FROM grn_items gi JOIN grn_master g ON g.id = gi.grn_id
           LEFT JOIN items i ON i.item_code = gi.item_code
           WHERE g.project_code = :pc AND g.grn_date = :dt
             AND COALESCE(g.status, 'Active') NOT IN ('Inactive', 'Deleted')
             AND COALESCE(gi.current_received_qty, 0) > 0""", p)
    machinery = _rows(
        """SELECT b.machinery_name AS machine, b.machinery_reg_no AS reg_no,
                  e.running_start_time::text AS start, e.running_finish_time::text AS finish,
                  e.project_sub_location AS location
           FROM log_book_entries e JOIN machinery_log_book b ON b.id = e.log_book_id
           WHERE e.project_code = :pc AND e.running_date = :dt
             AND COALESCE(e.status, 'Active') NOT IN ('Inactive', 'Deleted')""", p)
    hindrances = _rows(
        """SELECT title_of_hindrance AS title, cause_of_hindrance AS cause
           FROM hindrance_register
           WHERE project_code = :pc AND hindrance_date = :dt AND COALESCE(status, 'Active') = 'Active'""", p)
    for r in materials:
        if r.get("quantity") is not None:
            r["quantity"] = float(r["quantity"])
    return {
        "labour": labour,
        "labour_total": sum(int(r["count"]) for r in labour),
        "concrete": concrete,
        "materials_received": materials,
        "machinery_log": machinery,
        "hindrances": hindrances,
    }


def build_day_input(project_code, day):
    project = _project(project_code)
    photos = SitePhoto.query.filter_by(project_code=project_code, report_date=day, status="Active") \
        .order_by(SitePhoto.taken_at.asc()).all()
    return project, photos, {
        "project": {"code": project_code, "name": project.project_name if project else None},
        "date": day.strftime("%d %b %Y (%A)"),
        "photos": [
            {
                "photo_id": p.id,
                "time": p.taken_at.strftime("%H:%M") if p.taken_at else None,
                "location": p.sub_location,
                "caption": p.caption,
                "taken_by": p.uploader.username if p.uploader else None,
                "on_site": p.on_site,
                "seen": p.ai_result if p.ai_status == "done" else None,
            }
            for p in photos
        ],
        "site_records": day_records(project_code, day),
    }


# ══════════════════════════════════════════════════════════════════
# Reports
# ══════════════════════════════════════════════════════════════════

def _next_dpr_no():
    db.session.execute(text("SELECT pg_advisory_xact_lock(480777)"))
    last = db.session.query(DailyProgressReport.dpr_no).order_by(DailyProgressReport.id.desc()).first()
    if not last:
        return "DPR0001"
    suffix = last[0][3:]
    return "DPR" + str(int(suffix) + 1).zfill(len(suffix))


def _parse_day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def generate_report(project_code, day, user=None, auto=False):
    """Write (or rewrite) the day's report with AI. Keeps it a Draft for review."""
    project = _project(project_code)
    if not project:
        return res("Project not found", [], 404)
    if user is not None and not can_add(project, user):
        return res("You can't write the DPR in this project", [], 403)
    if day is None:
        return res("date required (YYYY-MM-DD)", [], 400)
    if day > ph.now_ist().date():
        return res("That day hasn't happened yet", [], 400)

    report = DailyProgressReport.query.filter_by(project_code=project_code, report_date=day).first()
    if report and report.workflow_status not in EDITABLE + ("Rejected",):
        return res(f"The report is already {report.workflow_status}", report_dict(report), 400)
    if auto and report and report.edited:
        return res("Kept the engineer's edited report", report_dict(report), 200)

    _, photos, day_input = build_day_input(project_code, day)
    records = day_input["site_records"]
    if not photos and not any(records[k] for k in ("labour", "concrete", "materials_received", "machinery_log", "hindrances")):
        return res("Nothing recorded on site for this day yet — add photos first", [], 400)
    waiting = sum(1 for p in photos if p.ai_status in ("pending", "working"))
    if waiting and not auto:
        return res(f"{waiting} photo(s) are still being read by AI — try again in a minute", {"waiting": waiting}, 409)

    try:
        out = ai.write_report(day_input)
    except ai.AiUnavailable as e:
        return res(f"AI is not available: {e}", [], 503)
    except ai.AiFailed as e:
        return res(f"AI could not write the report: {e}", [], 502)

    valid_ids = {p.id for p in photos}
    def _ids(lst):
        return [i for i in (lst or []) if i in valid_ids]
    for w in out.get("work_done", []):
        w["photo_ids"] = _ids(w.get("photo_ids"))
    for s in out.get("safety", []):
        s["photo_ids"] = _ids(s.get("photo_ids"))

    if not report:
        report = DailyProgressReport(
            dpr_no=_next_dpr_no(),
            dpr_uuid=str(_uuid.uuid4()),
            project_code=project_code,
            report_date=day,
            created_by=user["id"] if user else None,
        )
        db.session.add(report)
    elif report.workflow_status == "Rejected":
        report.status, report.current_level, report.locked = "Active", 0, False

    report.workflow_status = "Reback" if report.workflow_status == "Reback" else "Draft"
    report.summary = out.get("summary")
    report.content = {k: out.get(k) for k in ("work_done", "manpower", "machinery", "materials", "issues", "safety")}
    report.weather = (out.get("weather") or "")[:200] or None
    report.manpower_total = (out.get("manpower") or {}).get("total")
    report.photo_count = len(photos)
    report.highlight_photo_ids = _ids(out.get("highlight_photo_ids"))[:6]
    report.generated_at = datetime.utcnow()
    report.generated_by = "auto" if auto else "manual"
    report.ai_model = ai.report_model()
    report.edited = False
    report.updated_by = user["id"] if user else report.updated_by
    db.session.commit()
    return res("Report written — review and submit", report_dict(report), 200)


def list_days(project_code, user, limit=90):
    """One row per day that has photos or a report, newest first."""
    project = _project(project_code)
    if not project:
        return res("Project not found", [], 404)
    if not can_view(project, user):
        return res("Access denied", [], 403)
    counts = _rows(
        """SELECT report_date AS day, COUNT(*) AS photos,
                  SUM(CASE WHEN ai_status IN ('pending', 'working') THEN 1 ELSE 0 END) AS waiting,
                  MIN(thumb_url) AS thumb
           FROM site_photos WHERE project_code = :pc AND status = 'Active'
           GROUP BY report_date""", {"pc": project_code})
    by_day = {r["day"]: r for r in counts}
    reports = {r.report_date: r for r in DailyProgressReport.query.filter(
        DailyProgressReport.project_code == project_code,
        DailyProgressReport.status == "Active",
    ).all()}
    out = []
    for day in sorted(set(by_day) | set(reports), reverse=True)[:limit]:
        c, r = by_day.get(day, {}), reports.get(day)
        out.append({
            "id": r.id if r else None,
            "reportDate": _iso(day),
            "dprNo": r.dpr_no if r else None,
            "uuid": r.dpr_uuid if r else None,
            "photoCount": int(c.get("photos") or 0),
            "photosWaitingForAi": int(c.get("waiting") or 0),
            "thumbUrl": c.get("thumb"),
            "summary": r.summary if r else None,
            "manpowerTotal": r.manpower_total if r else None,
            "workflowStatus": r.workflow_status if r else "No report",
        })
    return res("DPR days", out, 200)


def get_day(project_code, day, user):
    project = _project(project_code)
    if not project:
        return res("Project not found", [], 404)
    if not can_view(project, user):
        return res("Access denied", [], 403)
    if day is None:
        return res("date required (YYYY-MM-DD)", [], 400)
    report = DailyProgressReport.query.filter_by(project_code=project_code, report_date=day).first()
    photos = SitePhoto.query.filter_by(project_code=project_code, report_date=day, status="Active") \
        .order_by(SitePhoto.taken_at.asc()).all()
    return res("DPR day", {
        "projectCode": project_code,
        "projectName": project.project_name,
        "reportDate": _iso(day),
        "report": report_dict(report) if report else None,
        "photos": [photo_dict(p) for p in photos],
        "siteRecords": day_records(project_code, day),
        "canEdit": can_add(project, user),
        "site": {
            "latitude": project.site_latitude,
            "longitude": project.site_longitude,
            "radiusM": project.site_radius_m or 500,
        },
    }, 200)


def get_details(report_id, user):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    return get_day(r.project_code, r.report_date, user)


def edit_report(report_id, data, user):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    if not can_add(_project(r.project_code), user):
        return res("Access denied", [], 403)
    if r.workflow_status not in EDITABLE:
        return res(f"The report is already {r.workflow_status}", [], 400)
    if "summary" in data:
        r.summary = (data.get("summary") or "").strip()
    if "remarks" in data:
        r.remarks = (data.get("remarks") or "").strip() or None
    if "weather" in data:
        r.weather = (data.get("weather") or "").strip()[:200] or None
    if isinstance(data.get("content"), dict):
        allowed = ("work_done", "manpower", "machinery", "materials", "issues", "safety")
        content = dict(r.content or {})
        content.update({k: v for k, v in data["content"].items() if k in allowed})
        r.content = content
        mp = content.get("manpower") or {}
        if isinstance(mp, dict) and mp.get("total") is not None:
            try:
                r.manpower_total = int(mp["total"])
            except (TypeError, ValueError):
                pass
    if isinstance(data.get("highlightPhotoIds"), list):
        r.highlight_photo_ids = [int(i) for i in data["highlightPhotoIds"] if str(i).isdigit()][:6]
    r.edited = True
    r.updated_by = user["id"]
    db.session.commit()
    return res("Report saved", report_dict(r), 200)


# ── Workflow (same steps as the other registers) ──────────────────

def submit_report(report_id, user_id):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    if r.workflow_status not in EDITABLE:
        return res("Report already submitted", [], 400)
    if not (r.summary or "").strip():
        return res("Write or generate the report before submitting", [], 400)
    if r.workflow_status == "Reback":
        r.current_level = 0
    first = get_first_approver(r.project_code, MODULE_CODE)
    now = datetime.utcnow()
    if not first:
        r.workflow_status, r.locked, r.approved_by, r.final_approved_at = "Approved", True, user_id, now
    else:
        r.workflow_status, r.current_level, r.locked = f"Pending_L{first.level_no}", first.level_no, True
    r.submitted_at, r.submitted_by, r.updated_by = now, user_id, user_id
    create_history(project_code=r.project_code, module_code=MODULE_CODE, record_id=r.id,
                   level_no=r.current_level, action="SUBMIT", action_by=user_id)
    db.session.commit()
    if first:
        _notify([first.user_id], f"DPR {r.report_date.strftime('%d %b')} needs your approval",
                 (r.summary or "")[:180], {"module": MODULE_CODE, "id": r.id})
    else:
        _notify_final(r)
    return res("Report submitted", {"id": r.id, "workflowStatus": r.workflow_status}, 200)


def _notify_final(r):
    project = _project(r.project_code)
    _notify(
        _recipients(r.project_code),
        f"DPR {r.report_date.strftime('%d %b')} — {project.project_name if project else r.project_code}",
        (r.summary or "")[:200],
        {"module": MODULE_CODE, "id": r.id, "uuid": r.dpr_uuid},
    )


def approve_report(report_id, user_id, comments=None):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    if not (r.workflow_status or "").startswith("Pending"):
        return res("Report is not pending", [], 400)
    if not is_current_approver(r.project_code, MODULE_CODE, r.current_level, user_id):
        return res("You are not the current approver", [], 403)
    gap = get_gap_level(r.project_code, MODULE_CODE, r.current_level)
    if gap:
        return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)
    nxt = get_next_approver(r.project_code, MODULE_CODE, r.current_level)
    create_history(project_code=r.project_code, module_code=MODULE_CODE, record_id=r.id,
                   level_no=r.current_level, action="APPROVE" if nxt else "FINAL_APPROVE",
                   action_by=user_id, comments=comments)
    if nxt:
        r.current_level, r.workflow_status = nxt.level_no, f"Pending_L{nxt.level_no}"
    else:
        r.workflow_status, r.locked, r.approved_by, r.final_approved_at = "Approved", True, user_id, datetime.utcnow()
    r.updated_by = user_id
    db.session.commit()
    if nxt:
        _notify([nxt.user_id], f"DPR {r.report_date.strftime('%d %b')} needs your approval",
                (r.summary or "")[:180], {"module": MODULE_CODE, "id": r.id})
    else:
        _notify_final(r)
    return res("Report approved", {"id": r.id, "workflowStatus": r.workflow_status}, 200)


def reback_report(report_id, user_id, comments=None):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    if not (r.workflow_status or "").startswith("Pending"):
        return res("Report is not pending", [], 400)
    if not comments:
        return res("Comments required", [], 400)
    if not is_current_approver(r.project_code, MODULE_CODE, r.current_level, user_id):
        return res("You are not the current approver", [], 403)
    r.workflow_status, r.locked, r.correction_sent_at, r.updated_by = "Reback", False, datetime.utcnow(), user_id
    create_history(project_code=r.project_code, module_code=MODULE_CODE, record_id=r.id,
                   level_no=r.current_level, action="REBACK", action_by=user_id, comments=comments)
    db.session.commit()
    if r.submitted_by:
        _notify([r.submitted_by], f"DPR {r.report_date.strftime('%d %b')} sent back for correction",
                comments[:180], {"module": MODULE_CODE, "id": r.id})
    return res("Report sent back for correction", {"id": r.id, "workflowStatus": r.workflow_status}, 200)


def reject_report(report_id, user_id, comments=None):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    if not (r.workflow_status or "").startswith("Pending"):
        return res("Report is not pending", [], 400)
    if not comments:
        return res("Comments required", [], 400)
    if not is_current_approver(r.project_code, MODULE_CODE, r.current_level, user_id):
        return res("You are not the current approver", [], 403)
    # Kept (one report per day); "Generate" turns a rejected report back into a draft.
    r.workflow_status, r.locked, r.rejected_at, r.rejected_by, r.updated_by = "Rejected", True, datetime.utcnow(), user_id, user_id
    create_history(project_code=r.project_code, module_code=MODULE_CODE, record_id=r.id,
                   level_no=r.current_level, action="REJECT", action_by=user_id, comments=comments)
    db.session.commit()
    if r.submitted_by:
        _notify([r.submitted_by], f"DPR {r.report_date.strftime('%d %b')} rejected",
                comments[:180], {"module": MODULE_CODE, "id": r.id})
    return res("Report rejected", {"id": r.id, "workflowStatus": r.workflow_status}, 200)


def history(report_id):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    rows = get_history(MODULE_CODE, r.id)
    return res("History", {
        "workflowStatus": r.workflow_status,
        "currentLevel": r.current_level,
        "approvalSteps": get_approval_steps(r.project_code, MODULE_CODE, r, rows),
        "history": [
            {
                "id": h.id, "action": h.action, "level": h.level_no, "comments": h.comments,
                "actionBy": h.user.username if h.user else None,
                "createdAt": h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else None,
            }
            for h in rows
        ],
    }, 200)


def my_approval_status(report_id, user_id):
    r = DailyProgressReport.query.get(report_id)
    if not r:
        return res("Report not found", [], 404)
    return res("Approval status", get_my_approval_status(r.project_code, MODULE_CODE, r, user_id), 200)


def by_uuid(report_uuid):
    """Public print page data (shared links / PDF), like the other registers."""
    r = DailyProgressReport.query.filter_by(dpr_uuid=report_uuid).first()
    if not r:
        return res("Report not found", [], 404)
    photos = SitePhoto.query.filter_by(project_code=r.project_code, report_date=r.report_date, status="Active") \
        .order_by(SitePhoto.taken_at.asc()).all()
    public = ("id", "takenAt", "subLocation", "caption", "fileUrl", "thumbUrl", "onSite", "timeVerified",
              "source", "latitude", "longitude", "uploadedBy", "ai")
    return res("DPR", {
        **report_dict(r),
        "projectDetails": {
            "name": r.project.project_name if r.project else None,
            "client": r.project.client_name if r.project else None,
            "address": r.project.registered_address if r.project else None,
        },
        "photos": [{k: v for k, v in photo_dict(p).items() if k in public} for p in photos],
        "siteRecords": day_records(r.project_code, r.report_date),
    }, 200)


# ══════════════════════════════════════════════════════════════════
# Scheduler: write the day's drafts in the evening
# ══════════════════════════════════════════════════════════════════

def auto_generate_today():
    day = ph.now_ist().date()
    codes = [r[0] for r in db.session.execute(
        text("SELECT DISTINCT project_code FROM site_photos WHERE report_date = :d AND status = 'Active'"),
        {"d": day},
    ).fetchall()]
    done = 0
    for code in codes:
        try:
            # Read any photos still waiting before writing.
            for (pid,) in db.session.execute(
                text("SELECT id FROM site_photos WHERE project_code = :pc AND report_date = :d "
                     "AND status = 'Active' AND ai_status = 'pending'"),
                {"pc": code, "d": day},
            ).fetchall():
                process_photo(pid)
            body, status = generate_report(code, day, user=None, auto=True)
            if status == 200 and body["data"] and not body["data"].get("edited"):
                done += 1
                r = DailyProgressReport.query.get(body["data"]["id"])
                project = _project(code)
                _notify(
                    _recipients(code),
                    f"Today's DPR is ready — {project.project_name if project else code}",
                    (r.summary or "")[:200] + " Review and submit.",
                    {"module": MODULE_CODE, "id": r.id, "date": _iso(day)},
                )
        except Exception:
            logger.exception("DPR auto-generate failed for %s", code)
            db.session.rollback()
    return done
