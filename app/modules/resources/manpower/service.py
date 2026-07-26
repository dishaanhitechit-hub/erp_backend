from datetime import datetime, date

from flask import g
from app.extensions import db
from app.response import res
from app.models.manpower import ManpowerWorker
from app.models.vendor import Vendor
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.resources.manpower.constants import LABOUR_CATEGORY_LIST


# ── Auto ID generator ─────────────────────────────────────────────────────────

def _generate_man_id():
    last = ManpowerWorker.query.order_by(ManpowerWorker.id.desc()).first()
    next_num = (last.id + 1) if last else 1
    return f"MAN{next_num:04d}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _upload(files, field):
    f = files.get(field)
    if f and f.filename:
        url = upload_file_to_bunny(f, folder="manpower")
        return url
    return None


def _serialize(w: ManpowerWorker):
    return {
        "id": w.id,
        "manId": w.man_id,
        "vendorId": w.vendor_id,
        "vendorName": w.vendor.ledger_name if w.vendor else None,
        "vendorCode": w.vendor.ledger_code if w.vendor else None,
        "fullName": w.full_name,
        "fatherName": w.father_name,
        "nominee": w.nominee,
        "address": w.address,
        "category": w.category,
        "categoryDisplay": LABOUR_CATEGORY_LIST.get(w.category, w.category),
        "ratePerManday": float(w.rate_per_manday) if w.rate_per_manday else None,
        "dateOfJoining": w.date_of_joining.isoformat() if w.date_of_joining else None,
        "aadharNumber": w.aadhar_number,
        "pan": w.pan,
        "uan": w.uan,
        "esic": w.esic,
        "bankAccountNumber": w.bank_account_number,
        "bankName": w.bank_name,
        "branchName": w.branch_name,
        "ifscCode": w.ifsc_code,
        "aadharFile": w.aadhar_file,
        "panFile": w.pan_file,
        "uanFile": w.uan_file,
        "esicFile": w.esic_file,
        "bankDetailsFile": w.bank_details_file,
        "status": w.status,
        "createdBy": w.created_by,
        "createdAt": w.created_at.isoformat() if w.created_at else None,
        "updatedAt": w.updated_at.isoformat() if w.updated_at else None,
    }


# ── GET category list ─────────────────────────────────────────────────────────

def get_labour_categories():
    data = [{"key": k, "label": v} for k, v in LABOUR_CATEGORY_LIST.items()]
    return res("Labour categories fetched", data, 200)


# ── CREATE ────────────────────────────────────────────────────────────────────

def create_manpower(request):
    data = request.form
    files = request.files

    category = data.get("category")
    if category and category not in LABOUR_CATEGORY_LIST:
        return res(
            f"Invalid category '{category}'. Allowed: {', '.join(LABOUR_CATEGORY_LIST.keys())}",
            [],
            400,
        )

    full_name = data.get("fullName", "").strip()
    if not full_name:
        return res("fullName is required", [], 400)

    worker = ManpowerWorker(
        man_id=_generate_man_id(),
        vendor_id=data.get("vendorId") or None,
        full_name=full_name,
        father_name=data.get("fatherName"),
        nominee=data.get("nominee"),
        address=data.get("address"),
        category=category,
        rate_per_manday=data.get("ratePerManday") or None,
        date_of_joining=_parse_date(data.get("dateOfJoining")),
        aadhar_number=data.get("aadharNumber"),
        pan=data.get("pan"),
        uan=data.get("uan"),
        esic=data.get("esic"),
        bank_account_number=data.get("bankAccountNumber"),
        bank_name=data.get("bankName"),
        branch_name=data.get("branchName"),
        ifsc_code=data.get("ifscCode"),
        aadhar_file=_upload(files, "aadharFile"),
        pan_file=_upload(files, "panFile"),
        uan_file=_upload(files, "uanFile"),
        esic_file=_upload(files, "esicFile"),
        bank_details_file=_upload(files, "bankDetailsFile"),
        created_by=g.current_user["id"],
    )

    db.session.add(worker)
    db.session.commit()

    return res("Manpower worker created", [_serialize(worker)], 201)


# ── LIST ──────────────────────────────────────────────────────────────────────

def get_all_manpower():
    workers = ManpowerWorker.query.order_by(ManpowerWorker.id.desc()).all()
    return res("Manpower workers fetched", [_serialize(w) for w in workers], 200)


# ── DETAIL ────────────────────────────────────────────────────────────────────

def get_manpower_by_id(worker_id):
    worker = ManpowerWorker.query.get(worker_id)
    if not worker:
        return res("Worker not found", [], 404)
    return res("Worker fetched", [_serialize(worker)], 200)


# ── UPDATE (only creator) ─────────────────────────────────────────────────────

def update_manpower(worker_id, request):
    worker = ManpowerWorker.query.get(worker_id)
    if not worker:
        return res("Worker not found", [], 404)

    # Only the creator of this record can edit it
    if worker.created_by != g.current_user["id"]:
        return res("Only the creator of this record can edit it", [], 403)

    data = request.form
    files = request.files

    category = data.get("category")
    if category and category not in LABOUR_CATEGORY_LIST:
        return res(
            f"Invalid category '{category}'. Allowed: {', '.join(LABOUR_CATEGORY_LIST.keys())}",
            [],
            400,
        )

    if "fullName" in data:
        full_name = data.get("fullName", "").strip()
        if not full_name:
            return res("fullName cannot be empty", [], 400)
        worker.full_name = full_name

    if "vendorId" in data:
        worker.vendor_id = data.get("vendorId") or None
    if "fatherName" in data:
        worker.father_name = data.get("fatherName")
    if "nominee" in data:
        worker.nominee = data.get("nominee")
    if "address" in data:
        worker.address = data.get("address")
    if category:
        worker.category = category
    if "ratePerManday" in data:
        worker.rate_per_manday = data.get("ratePerManday") or None
    if "dateOfJoining" in data:
        worker.date_of_joining = _parse_date(data.get("dateOfJoining"))
    if "aadharNumber" in data:
        worker.aadhar_number = data.get("aadharNumber")
    if "pan" in data:
        worker.pan = data.get("pan")
    if "uan" in data:
        worker.uan = data.get("uan")
    if "esic" in data:
        worker.esic = data.get("esic")
    if "bankAccountNumber" in data:
        worker.bank_account_number = data.get("bankAccountNumber")
    if "bankName" in data:
        worker.bank_name = data.get("bankName")
    if "branchName" in data:
        worker.branch_name = data.get("branchName")
    if "ifscCode" in data:
        worker.ifsc_code = data.get("ifscCode")

    new_aadhar = _upload(files, "aadharFile")
    if new_aadhar:
        worker.aadhar_file = new_aadhar

    new_pan = _upload(files, "panFile")
    if new_pan:
        worker.pan_file = new_pan

    new_uan = _upload(files, "uanFile")
    if new_uan:
        worker.uan_file = new_uan

    new_esic = _upload(files, "esicFile")
    if new_esic:
        worker.esic_file = new_esic

    new_bank = _upload(files, "bankDetailsFile")
    if new_bank:
        worker.bank_details_file = new_bank

    worker.updated_at = datetime.utcnow()
    db.session.commit()

    return res("Worker updated", [_serialize(worker)], 200)
