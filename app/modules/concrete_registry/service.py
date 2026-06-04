from datetime import datetime, time

from app.extensions import db
from app.response import res
from app.models.project import Project
from app.cloudinary_uploader import upload_file_to_bunny
from app.models.concrete_registry import ConcreteRegistry


def _fmt_date(t):
    if t is None:
        return None
    if isinstance(t, (t, time)):
        return t.strftime("%H.%M.%S")
    return t


def _registry_dict(r):
    return {
        "id": r.id,
        "projectCode": r.projectcode,
        "referenceOrderNo": r.reference_order_no,
        "projectSubLocation": r.project_sub_location,
        "segment": r.segment,
        "pouringDate": _fmt_date(r.pouring_date),
        "pouringStartDate": _fmt_date(r.pouring_start_date),
        "pouringEndDate": _fmt_date(r.pouring_end_date),
        "gradeConcrete": r.grade_concrete,
        "concreteVolume": r.concrete_volume,
        "requisitionNo": r.requisition_no,
        "requisitionBy": r.requisition_by,
        "vehicleNumber": r.vehicle_number,
        "batchNo": r.batch_no,
        "attachBatchFile": r.attach_batch_file,
    }


def generate_reg_no(project_code):
    last_reg = (
        db.session.query(ConcreteRegistry.reference_order_no)
        .filter(ConcreteRegistry.projectcode == project_code)
        .order_by(ConcreteRegistry.id.desc())
        .first()
    )

    if last_reg:
        try:
            last_serial = int(last_reg[0][2:])
        except (ValueError, TypeError):
            last_serial = 0
    else:
        last_serial = 0

    return f"71{last_serial + 1:04d}"


def create_resigistry(request):
    data = request.form
    file = request.files
    try:
        pc = data.get("projectCode")
        project = Project.query.filter_by(projectcode=pc).first()
        if not project:
            return res("Invalid Project Code", [], 400)

        xtmp = generate_reg_no(pc)
        attach_file = file.get("attachBatchFile")
        batch_file = upload_file_to_bunny(
            file=attach_file,
            mainFolder="concrete_registry",
            subFolder=xtmp,
            fileName="attach_file"
        )

        registry = ConcreteRegistry(
            projectcode=pc,
            reference_order_no=xtmp,
            project_sub_location=data.get("projectSubLocation"),
            segment=data.get("segment"),
            pouring_date=data.get("pouringDate"),
            pouring_start_date=data.get("pouringStartDate"),
            pouring_end_date=data.get("pouringEndDate"),
            grade_concrete=data.get("gradeConcrete"),
            concrete_volume=data.get("concreteVolume"),
            attach_batch_file=batch_file,
            requisition_no=data.get("requisitionNo"),
            requisition_by=data.get("requisitionBy"),
            vehicle_number=data.get("vehicleNumber"),
            batch_no=data.get("batchNo"),
        )

        db.session.add(registry)
        db.session.commit()

        return res("Concrete Registry created", [_registry_dict(registry)], 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def get_registry_list(request):
    try:
        project_code = request.args.get("projectCode")
        query = ConcreteRegistry.query
        if project_code:
            query = query.filter_by(projectcode=project_code)
        registries = query.order_by(ConcreteRegistry.id.desc()).all()
        data = [_registry_dict(r) for r in registries]
        return res("Concrete Registry list", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


def get_registry_by_id(registry_id):
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)
        return res("Concrete Registry details", [_registry_dict(registry)], 200)
    except Exception as e:
        return res(str(e), [], 500)


def update_registry(registry_id, request):
    data = request.form
    file = request.files
    try:
        registry = ConcreteRegistry.query.get(registry_id)
        if not registry:
            return res("Concrete Registry not found", [], 404)

        if data.get("projectSubLocation"):
            registry.project_sub_location = data.get("projectSubLocation")
        if data.get("segment"):
            registry.segment = data.get("segment")
        if data.get("pouringDate"):
            registry.pouring_date = data.get("pouringDate")
        if data.get("pouringStartDate"):
            registry.pouring_start_date = data.get("pouringStartDate")
        if data.get("pouringEndDate"):
            registry.pouring_end_date = data.get("pouringEndDate")
        if data.get("gradeConcrete"):
            registry.grade_concrete = data.get("gradeConcrete")
        if data.get("concreteVolume"):
            registry.concrete_volume = data.get("concreteVolume")
        if data.get("requisitionNo"):
            registry.requisition_no = data.get("requisitionNo")
        if data.get("requisitionBy"):
            registry.requisition_by = data.get("requisitionBy")
        if data.get("vehicleNumber"):
            registry.vehicle_number = data.get("vehicleNumber")
        if data.get("batchNo"):
            registry.batch_no = data.get("batchNo")

        attach_file = file.get("attachBatchFile")
        if attach_file:
            batch_file = upload_file_to_bunny(
                file=attach_file,
                mainFolder="concrete_registry",
                subFolder=registry.reference_order_no,
                fileName="attach_file"
            )
            registry.attach_batch_file = batch_file

        db.session.commit()
        return res("Concrete Registry updated", [_registry_dict(registry)], 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
