import json
from flask import g, request as flask_request
from sqlalchemy import text
from app.response import res
from app.extensions import db
from app.models.supplier import Supplier, SupplierLedgerMap, SupplierProjectMap
from app.models.vendor import Vendor
from app.models.project import Project
from app.modules.work_flow import is_creator

_SUPPLIER_MODULE_CODES = [
    "contact_dairy_work_force",
    "contact_dairy_materials",
    "contact_dairy_plant_machinery",
]


def _check_supplier_creator(project_code, user_id):
    return any(is_creator(project_code, code, user_id) for code in _SUPPLIER_MODULE_CODES)


NATURE_OF_SERVICE_MAP = {
    "Materials": [
        "Cement & Binding Materials",
        "Reinforcement Steel",
        "Aggregates",
        "Bricks & Blocks",
        "Ready-mix Concrete",
        "Structural Steel Materials",
        "Shuttering & Formwork Materials",
        "Doors & Windows",
        "Waterproofing Materials",
        "Hardware",
        "Roofing & Cladding Materials",
        "Machinery & Spare Parts",
        "Tools & Tackles",
        "Safety Items (PPE)",
        "Electrical Materials",
        "Machinery Materials",
        "Plumbing Materials",
        "Fabrication Materials",
        "Fuels & Lubricants",
        "Construction Chemicals",
    ],
    "Work_Force": [
        "Aluminum Glazing Gang",
        "Concreting Gang",
        "Electrical Fitting Gang",
        "EPBX Gang",
        "Facade or Cladding Gang",
        "False Ceiling Gang",
        "Fire Fighting Gang",
        "Masonry Gang",
        "Others Specialized Gang",
        "Painting Gang",
        "Plumbing Gang",
        "Road Construction Gang",
        "Scaffolding Gang",
        "Shuttering & Reinforcement Gang",
        "Structural Fabrication & Erection Gang",
        "Tiles Flooring Gang",
        "Un-Skill Gang",
        "VDF Flooring Gang",
        "Welding Gang",
        "Wooden Carpentry Gang",
    ],
    "Plant_Machinery": [
        "Earthmoving Equipment",
        "Lifting Equipment",
        "Compaction Equipment",
        "Concrete Equipment",
        "Road Construction Equipment",
        "Drilling and Foundation Equipment",
        "Material Handling Equipment",
        "Demolition Equipment",
        "Transportation Equipment",
        "Site Utility Equipment",
        "Reinforcement & Fabrication Equipment",
        "Surveying Equipment",
        "Miscellaneous Equipment",
    ],
    "others": [],
}


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def generate_supplier_code():
    last = Supplier.query.order_by(Supplier.id.desc()).first()
    if not last:
        return "SUP0001"
    try:
        num = int(last.supplier_code.replace("SUP", ""))
    except Exception:
        num = 0
    return f"SUP{num + 1:04d}"


def _supplier_dict(supplier):
    ledgers = []
    for m in supplier.ledger_mappings:
        v = m.vendor
        if v:
            ledgers.append({
                "ledgerId": v.id,
                "ledgerCode": v.ledger_code,
                "ledgerName": v.ledger_name,
            })

    projects = []
    for pm in supplier.project_mappings:
        projects.append({
            "projectId": pm.project_id,
            "projectCode": pm.project_code,
            "assignedAt": pm.assigned_at,
        })

    return {
        "supplierId": supplier.id,
        "supplierCode": supplier.supplier_code,
        "supplierName": supplier.supplier_name,
        "registeredAddress": supplier.registered_address,
        "corporateAddress": supplier.corporate_address,
        "contactPerson": supplier.contact_person,
        "designation": supplier.designation,
        "mobileNumber": supplier.mobile_number,
        "whatsappNumber": supplier.whatsapp_number,
        "email": supplier.email,
        "supplierTypes": supplier.supplier_types or [],
        "natureOfService": supplier.nature_of_service or [],
        "serviceDescription": supplier.service_description,
        "linkedLedgers": ledgers,
        "linkedProjects": projects,
        "status": supplier.status,
        "createdAt": supplier.created_at,
    }


def _get_current_user():
    cu = g.current_user if hasattr(g, "current_user") else {}
    return cu.get("id"), cu.get("projectId")


# ─────────────────────────────────────────
# NATURE OF SERVICE LIST
# ─────────────────────────────────────────

def get_nature_of_service():
    types_param = flask_request.args.get("types", "")
    if not types_param:
        return res("types query param is required", [], 400)

    merged = []
    seen = set()
    for t in types_param.split(","):
        key = t.strip()
        for item in NATURE_OF_SERVICE_MAP.get(key, []):
            if item not in seen:
                seen.add(item)
                merged.append(item)

    return res("nature of service list", merged, 200)


# ─────────────────────────────────────────
# CREATE SUPPLIER
# ─────────────────────────────────────────

def create_supplier(request):
    data = request.json or {}

    user_id, project_id = _get_current_user()
    project = Project.query.get(project_id) if project_id else None
    project_code = project.project_code if project else None

    if not _check_supplier_creator(project_code, user_id):
        return res("You are not authorized to create supplier", [], 403)

    supplier_name = data.get("supplierName", "").strip()
    if not supplier_name:
        return res("supplierName is required", [], 400)

    supplier = Supplier(
        supplier_code=generate_supplier_code(),
        supplier_name=supplier_name,
        registered_address=data.get("registeredAddress"),
        corporate_address=data.get("corporateAddress"),
        contact_person=data.get("contactPerson"),
        designation=data.get("designation"),
        mobile_number=data.get("mobileNumber"),
        whatsapp_number=data.get("whatsappNumber"),
        email=data.get("email"),
        supplier_types=data.get("supplierTypes", []),
        nature_of_service=data.get("natureOfService", []),
        service_description=data.get("serviceDescription"),
        created_by=user_id,
    )

    db.session.add(supplier)
    db.session.flush()

    # Auto-assign to current project if project context exists
    if project:
        db.session.add(SupplierProjectMap(
            supplier_id=supplier.id,
            project_id=project.id,
            project_code=project.project_code,
        ))

    # Link ledger IDs if provided
    for lid in data.get("ledgerIds", []):
        if Vendor.query.get(lid):
            db.session.add(SupplierLedgerMap(supplier_id=supplier.id, ledger_id=lid))

    db.session.commit()
    return res("supplier created successfully", [_supplier_dict(supplier)], 201)


# ─────────────────────────────────────────
# GET ALL SUPPLIERS
# ─────────────────────────────────────────

def get_all_suppliers():
    supplier_type = flask_request.args.get("supplierType")
    search = flask_request.args.get("search", "").strip()

    user_id, project_id = _get_current_user()

    query = Supplier.query
    if project_id:
        query = query.join(
            SupplierProjectMap,
            SupplierProjectMap.supplier_id == Supplier.id
        ).filter(SupplierProjectMap.project_id == project_id)

    if supplier_type:
        query = query.filter(
            text("suppliers.supplier_types::jsonb @> CAST(:val AS jsonb)").bindparams(
                val=json.dumps([supplier_type])
            )
        )
    if search:
        query = query.filter(Supplier.supplier_name.ilike(f"%{search}%"))

    suppliers = query.order_by(Supplier.id.desc()).all()
    return res("supplier list fetched successfully", [_supplier_dict(s) for s in suppliers], 200)


# ─────────────────────────────────────────
# GET SUPPLIER BY ID
# ─────────────────────────────────────────

def get_supplier_by_id(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return res("supplier not found", [], 404)
    return res("supplier fetched successfully", [_supplier_dict(supplier)], 200)


# ─────────────────────────────────────────
# UPDATE SUPPLIER
# ─────────────────────────────────────────

def update_supplier(supplier_id, request):
    data = request.json or {}
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return res("supplier not found", [], 404)

    user_id, project_id = _get_current_user()
    project = Project.query.get(project_id) if project_id else None
    project_code = project.project_code if project else None

    if not _check_supplier_creator(project_code, user_id):
        return res("You are not authorized to update supplier", [], 403)

    supplier.supplier_name = data.get("supplierName", supplier.supplier_name)
    supplier.registered_address = data.get("registeredAddress", supplier.registered_address)
    supplier.corporate_address = data.get("corporateAddress", supplier.corporate_address)
    supplier.contact_person = data.get("contactPerson", supplier.contact_person)
    supplier.designation = data.get("designation", supplier.designation)
    supplier.mobile_number = data.get("mobileNumber", supplier.mobile_number)
    supplier.whatsapp_number = data.get("whatsappNumber", supplier.whatsapp_number)
    supplier.email = data.get("email", supplier.email)
    supplier.service_description = data.get("serviceDescription", supplier.service_description)

    if "supplierTypes" in data:
        supplier.supplier_types = data["supplierTypes"]
    if "natureOfService" in data:
        supplier.nature_of_service = data["natureOfService"]

    sync_supplier_to_vendors(supplier)
    db.session.commit()
    return res("supplier updated successfully", [_supplier_dict(supplier)], 200)


# ─────────────────────────────────────────
# DELETE SUPPLIER
# ─────────────────────────────────────────

def delete_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return res("supplier not found", [], 404)

    user_id, project_id = _get_current_user()
    project = Project.query.get(project_id) if project_id else None
    project_code = project.project_code if project else None

    if not _check_supplier_creator(project_code, user_id):
        return res("You are not authorized to delete supplier", [], 403)

    db.session.delete(supplier)
    db.session.commit()
    return res("supplier deleted successfully", [], 200)


# ─────────────────────────────────────────
# BULK ASSIGN SUPPLIERS TO PROJECTS (admin only)
# ─────────────────────────────────────────

def bulk_assign_projects(request):
    data = request.json or {}
    supplier_ids = data.get("supplierIds", [])
    project_ids = data.get("projectIds", [])

    if not supplier_ids or not project_ids:
        return res("supplierIds and projectIds are required", [], 400)

    project_map = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()}
    supplier_ids_valid = [s.id for s in Supplier.query.filter(Supplier.id.in_(supplier_ids)).all()]

    added = 0
    skipped = 0
    for sid in supplier_ids_valid:
        for pid in project_ids:
            project = project_map.get(pid)
            if not project:
                skipped += 1
                continue
            existing = SupplierProjectMap.query.filter_by(
                supplier_id=sid, project_id=pid
            ).first()
            if existing:
                skipped += 1
                continue
            db.session.add(SupplierProjectMap(
                supplier_id=sid,
                project_id=pid,
                project_code=project.project_code,
            ))
            added += 1

    db.session.commit()
    return res("bulk assign completed", [{"added": added, "skipped": skipped}], 200)


# ─────────────────────────────────────────
# BULK REMOVE SUPPLIERS FROM PROJECTS (admin only)
# ─────────────────────────────────────────

def bulk_remove_projects(request):
    data = request.json or {}
    supplier_ids = data.get("supplierIds", [])
    project_ids = data.get("projectIds", [])

    if not supplier_ids or not project_ids:
        return res("supplierIds and projectIds are required", [], 400)

    removed = 0
    for sid in supplier_ids:
        for pid in project_ids:
            mapping = SupplierProjectMap.query.filter_by(
                supplier_id=sid, project_id=pid
            ).first()
            if mapping:
                db.session.delete(mapping)
                removed += 1

    db.session.commit()
    return res("bulk remove completed", [{"removed": removed}], 200)


# ─────────────────────────────────────────
# LINK LEDGER TO SUPPLIER
# ─────────────────────────────────────────

def link_ledger(supplier_id, request):
    data = request.json or {}
    ledger_id = data.get("ledgerId")
    if not ledger_id:
        return res("ledgerId is required", [], 400)

    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return res("supplier not found", [], 404)

    user_id, project_id = _get_current_user()
    project = Project.query.get(project_id) if project_id else None
    project_code = project.project_code if project else None

    if not _check_supplier_creator(project_code, user_id):
        return res("You are not authorized to link ledger", [], 403)

    vendor = Vendor.query.get(ledger_id)
    if not vendor:
        return res("ledger not found", [], 404)

    existing = SupplierLedgerMap.query.filter_by(
        supplier_id=supplier_id, ledger_id=ledger_id
    ).first()
    if existing:
        return res("ledger already linked to this supplier", [], 409)

    db.session.add(SupplierLedgerMap(supplier_id=supplier_id, ledger_id=ledger_id))
    db.session.commit()
    return res("ledger linked successfully", [_supplier_dict(supplier)], 200)


# ─────────────────────────────────────────
# UNLINK LEDGER FROM SUPPLIER
# ─────────────────────────────────────────

def unlink_ledger(supplier_id, ledger_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return res("supplier not found", [], 404)

    user_id, project_id = _get_current_user()
    project = Project.query.get(project_id) if project_id else None
    project_code = project.project_code if project else None

    if not _check_supplier_creator(project_code, user_id):
        return res("You are not authorized to unlink ledger", [], 403)

    mapping = SupplierLedgerMap.query.filter_by(
        supplier_id=supplier_id, ledger_id=ledger_id
    ).first()
    if not mapping:
        return res("mapping not found", [], 404)

    db.session.delete(mapping)
    db.session.commit()
    return res("ledger unlinked successfully", [], 200)


# ─────────────────────────────────────────
# SYNC FUNCTIONS (called internally)
# ─────────────────────────────────────────

def sync_vendor_to_suppliers(vendor):
    mappings = SupplierLedgerMap.query.filter_by(ledger_id=vendor.id).all()
    for m in mappings:
        supplier = m.supplier
        if supplier:
            supplier.supplier_name = vendor.ledger_name
            supplier.registered_address = vendor.registered_address
            supplier.corporate_address = vendor.corporate_address
            supplier.contact_person = vendor.primary_contact_person
            supplier.designation = vendor.designation
            supplier.mobile_number = vendor.primary_contact_number
            supplier.whatsapp_number = vendor.whatsapp_number
            supplier.email = vendor.email
            supplier.supplier_types = vendor.supplier_types
            supplier.nature_of_service = vendor.nature_of_service
            supplier.service_description = vendor.service_description


def sync_supplier_to_vendors(supplier):
    mappings = SupplierLedgerMap.query.filter_by(supplier_id=supplier.id).all()
    for m in mappings:
        vendor = m.vendor
        if vendor:
            vendor.supplier_types = supplier.supplier_types
            vendor.nature_of_service = supplier.nature_of_service
            vendor.service_description = supplier.service_description


def auto_create_or_link_supplier(vendor, existing_supplier_id=None):
    if existing_supplier_id:
        supplier = Supplier.query.get(existing_supplier_id)
        if supplier:
            existing_map = SupplierLedgerMap.query.filter_by(
                supplier_id=existing_supplier_id, ledger_id=vendor.id
            ).first()
            if not existing_map:
                db.session.add(SupplierLedgerMap(supplier_id=existing_supplier_id, ledger_id=vendor.id))
            vendor.supplier_id = existing_supplier_id
        return

    if vendor.supplier_id:
        return

    supplier = Supplier(
        supplier_code=generate_supplier_code(),
        supplier_name=vendor.ledger_name,
        registered_address=vendor.registered_address,
        corporate_address=vendor.corporate_address,
        contact_person=vendor.primary_contact_person,
        designation=vendor.designation,
        mobile_number=vendor.primary_contact_number,
        whatsapp_number=vendor.whatsapp_number,
        email=vendor.email,
        supplier_types=vendor.supplier_types,
        nature_of_service=vendor.nature_of_service,
        service_description=vendor.service_description,
        created_by=vendor.created_by,
    )
    db.session.add(supplier)
    db.session.flush()

    db.session.add(SupplierLedgerMap(supplier_id=supplier.id, ledger_id=vendor.id))
    vendor.supplier_id = supplier.id
