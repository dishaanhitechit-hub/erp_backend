from datetime import datetime

from app.extensions import db
from app.response import res
from app.models.pmMaster import PMMaster
from app.cloudinary_uploader import upload_file_to_bunny


def _generate_pm_uid():
    last = PMMaster.query.order_by(PMMaster.id.desc()).first()
    next_num = (last.id + 1) if last else 1
    return f"PM{next_num:04d}"


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _serialize(p: PMMaster):
    return {
        "id":                 p.id,
        "pmUid":              p.pm_uid,
        "machineName":        p.machine_name,
        "machineryType":      p.machinery_type,
        "registrationNumber": p.registration_number,
        "registrationDate":   p.registration_date.isoformat() if p.registration_date else None,
        "registrationFile":   p.registration_file,
        "insuranceNumber":    p.insurance_number,
        "insuranceDate":      p.insurance_date.isoformat() if p.insurance_date else None,
        "insuranceFile":      p.insurance_file,
        "pucCertNumber":      p.puc_cert_number,
        "pucDate":            p.puc_date.isoformat() if p.puc_date else None,
        "pucFile":            p.puc_file,
        "roadTaxNumber":      p.road_tax_number,
        "roadTaxDate":        p.road_tax_date.isoformat() if p.road_tax_date else None,
        "roadTaxFile":        p.road_tax_file,
        "fuelConsumptionUnit":  p.fuel_consumption_unit,
        "purchasedBillAmount":  float(p.purchased_bill_amount) if p.purchased_bill_amount else None,
        "purchasedBillDate":    p.purchased_bill_date.isoformat() if p.purchased_bill_date else None,
        "purchasedBillFile":    p.purchased_bill_file,
        "status":             p.status,
        "createdAt":          p.created_at.isoformat() if p.created_at else None,
        "updatedAt":          p.updated_at.isoformat() if p.updated_at else None,
    }


# ── CREATE ────────────────────────────────────────────────────────────────────

def create_pm_id(request, user_id):
    try:
        data  = request.form
        files = request.files

        pm_uid = _generate_pm_uid()

        def _upload(file_key, label):
            f = files.get(file_key)
            return upload_file_to_bunny(f, "machinery", pm_uid, label) if f else None

        pm = PMMaster(
            pm_uid              = pm_uid,
            machine_name        = data.get("machineName"),
            machinery_type      = data.get("machineryType"),
            registration_number = data.get("registrationNumber"),
            registration_date   = _parse_date(data.get("registrationDate")),
            registration_file   = _upload("registrationFile", "registration"),
            insurance_number    = data.get("insuranceNumber"),
            insurance_date      = _parse_date(data.get("insuranceDate")),
            insurance_file      = _upload("insuranceFile", "insurance"),
            puc_cert_number     = data.get("pucCertNumber"),
            puc_date            = _parse_date(data.get("pucDate")),
            puc_file            = _upload("pucFile", "puc"),
            road_tax_number     = data.get("roadTaxNumber"),
            road_tax_date       = _parse_date(data.get("roadTaxDate")),
            road_tax_file       = _upload("roadTaxFile", "road_tax"),
            fuel_consumption_unit  = data.get("fuelConsumptionUnit"),
            purchased_bill_amount  = data.get("purchasedBillAmount") or None,
            purchased_bill_date    = _parse_date(data.get("purchasedBillDate")),
            purchased_bill_file    = _upload("purchasedBillFile", "purchased_bill"),
            created_by          = user_id,
        )

        db.session.add(pm)
        db.session.commit()

        return res("Machinery ID created", {"id": pm.id, "pmUid": pm.pm_uid}, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ── LIST / SUMMARY ────────────────────────────────────────────────────────────

def get_pm_id_list():
    try:
        rows = PMMaster.query.filter_by(status="Active").order_by(PMMaster.id.desc()).all()
        data = []
        for p in rows:
            data.append({
                "id":                   p.id,
                "pmUid":                p.pm_uid,
                "machineId":            p.pm_uid,
                "machineName":          p.machine_name,
                "machineryType":        p.machinery_type,
                "registrationNumber":   p.registration_number,
                "registrationValidity": p.registration_date.isoformat() if p.registration_date else None,
                "insuranceValidity":    p.insurance_date.isoformat() if p.insurance_date else None,
                "pucValidity":          p.puc_date.isoformat() if p.puc_date else None,
                "roadTaxValidity":      p.road_tax_date.isoformat() if p.road_tax_date else None,
            })
        return res("Machinery ID list fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── DETAIL ────────────────────────────────────────────────────────────────────

def get_pm_id_detail(pm_id):
    try:
        p = PMMaster.query.get(pm_id)
        if not p:
            return res("Machinery ID not found", [], 404)
        return res("Machinery ID fetched", _serialize(p), 200)

    except Exception as e:
        return res(str(e), [], 500)


def get_pm_id_by_uid(pm_uid):
    try:
        p = PMMaster.query.filter_by(pm_uid=pm_uid).first()
        if not p:
            return res("Machinery not found", [], 404)
        return res("Machinery fetched", _serialize(p), 200)

    except Exception as e:
        return res(str(e), [], 500)


# ── EDIT ──────────────────────────────────────────────────────────────────────

def edit_pm_id(pm_id, request, user_id):
    try:
        p = PMMaster.query.get(pm_id)
        if not p:
            return res("Machinery ID not found", [], 404)

        data  = request.form
        files = request.files

        def _upload(file_key, label):
            f = files.get(file_key)
            return upload_file_to_bunny(f, "machinery", p.pm_uid, label) if f else None

        if data.get("machineName"):
            p.machine_name = data.get("machineName")
        if data.get("machineryType"):
            p.machinery_type = data.get("machineryType")

        if data.get("registrationNumber"):
            p.registration_number = data.get("registrationNumber")
        if data.get("registrationDate"):
            p.registration_date = _parse_date(data.get("registrationDate"))
        new_reg_file = _upload("registrationFile", "registration")
        if new_reg_file:
            p.registration_file = new_reg_file

        if data.get("insuranceNumber"):
            p.insurance_number = data.get("insuranceNumber")
        if data.get("insuranceDate"):
            p.insurance_date = _parse_date(data.get("insuranceDate"))
        new_ins_file = _upload("insuranceFile", "insurance")
        if new_ins_file:
            p.insurance_file = new_ins_file

        if data.get("pucCertNumber"):
            p.puc_cert_number = data.get("pucCertNumber")
        if data.get("pucDate"):
            p.puc_date = _parse_date(data.get("pucDate"))
        new_puc_file = _upload("pucFile", "puc")
        if new_puc_file:
            p.puc_file = new_puc_file

        if data.get("roadTaxNumber"):
            p.road_tax_number = data.get("roadTaxNumber")
        if data.get("roadTaxDate"):
            p.road_tax_date = _parse_date(data.get("roadTaxDate"))
        new_road_file = _upload("roadTaxFile", "road_tax")
        if new_road_file:
            p.road_tax_file = new_road_file

        if data.get("fuelConsumptionUnit"):
            p.fuel_consumption_unit = data.get("fuelConsumptionUnit")

        if data.get("purchasedBillAmount") is not None:
            p.purchased_bill_amount = data.get("purchasedBillAmount") or None
        if data.get("purchasedBillDate"):
            p.purchased_bill_date = _parse_date(data.get("purchasedBillDate"))
        new_bill_file = _upload("purchasedBillFile", "purchased_bill")
        if new_bill_file:
            p.purchased_bill_file = new_bill_file

        p.updated_by = user_id
        p.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Machinery ID updated", {"id": p.id, "pmUid": p.pm_uid}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
