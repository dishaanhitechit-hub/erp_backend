import json
from flask import g, request as flask_request
from app.response import res
from app.extensions import db
from app.models.supplier import Supplier, SupplierLedgerMap
from app.models.vendor import Vendor


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
    "Plant_Machinery": [],
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
    ledger_ids = [m.ledger_id for m in supplier.ledger_mappings]
    ledgers = []
    for m in supplier.ledger_mappings:
        v = m.vendor
        if v:
            ledgers.append({
                "ledgerId": v.id,
                "ledgerCode": v.ledger_code,
                "ledgerName": v.ledger_name,
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
        "natureOfService": supplier.nature_of_service,
        "serviceDescription": supplier.service_description,
        "linkedLedgers": ledgers,
        "status": supplier.status,
        "createdAt": supplier.created_at,
    }


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
        key = t.strip().lower().replace("-", "_").replace(" ", "_")
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

    supplier = Supplier(
        supplier_code=generate_supplier_code(),
        supplier_name=data.get("supplierName", "").strip(),
        registered_address=data.get("registeredAddress"),
        corporate_address=data.get("corporateAddress"),
        contact_person=data.get("contactPerson"),
        designation=data.get("designation"),
        mobile_number=data.get("mobileNumber"),
        whatsapp_number=data.get("whatsappNumber"),
        email=data.get("email"),
        supplier_types=data.get("supplierTypes", []),
        nature_of_service=data.get("natureOfService"),
        service_description=data.get("serviceDescription"),
    )

    if not supplier.supplier_name:
        return res("supplierName is required", [], 400)

    if hasattr(g, "current_user"):
        supplier.created_by = g.current_user.get("id")

    db.session.add(supplier)
    db.session.flush()  # get supplier.id before mapping

    # Link ledger IDs if provided
    ledger_ids = data.get("ledgerIds", [])
    for lid in ledger_ids:
        vendor = Vendor.query.get(lid)
        if vendor:
            db.session.add(SupplierLedgerMap(supplier_id=supplier.id, ledger_id=lid))

    db.session.commit()
    return res("supplier created successfully", [_supplier_dict(supplier)], 201)


# ─────────────────────────────────────────
# GET ALL SUPPLIERS
# ─────────────────────────────────────────

def get_all_suppliers():
    supplier_type = flask_request.args.get("supplierType")

    query = Supplier.query
    if supplier_type:
        query = query.filter(Supplier.supplier_types.contains([supplier_type]))

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

    supplier.supplier_name = data.get("supplierName", supplier.supplier_name)
    supplier.registered_address = data.get("registeredAddress", supplier.registered_address)
    supplier.corporate_address = data.get("corporateAddress", supplier.corporate_address)
    supplier.contact_person = data.get("contactPerson", supplier.contact_person)
    supplier.designation = data.get("designation", supplier.designation)
    supplier.mobile_number = data.get("mobileNumber", supplier.mobile_number)
    supplier.whatsapp_number = data.get("whatsappNumber", supplier.whatsapp_number)
    supplier.email = data.get("email", supplier.email)
    supplier.nature_of_service = data.get("natureOfService", supplier.nature_of_service)
    supplier.service_description = data.get("serviceDescription", supplier.service_description)

    if "supplierTypes" in data:
        supplier.supplier_types = data["supplierTypes"]

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
    db.session.delete(supplier)
    db.session.commit()
    return res("supplier deleted successfully", [], 200)


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
    mapping = SupplierLedgerMap.query.filter_by(
        supplier_id=supplier_id, ledger_id=ledger_id
    ).first()
    if not mapping:
        return res("mapping not found", [], 404)

    db.session.delete(mapping)
    db.session.commit()
    return res("ledger unlinked successfully", [], 200)


# ─────────────────────────────────────────
# SYNC FROM VENDOR (called internally when vendor is updated)
# Pushes common fields to all mapped suppliers
# ─────────────────────────────────────────

def sync_vendor_to_suppliers(vendor):
    """Vendor → Supplier: push common + supplier-specific fields to all mapped suppliers."""
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
    # caller must commit


def sync_supplier_to_vendors(supplier):
    """Supplier → Vendor: push supplier-specific fields to all mapped vendors."""
    mappings = SupplierLedgerMap.query.filter_by(supplier_id=supplier.id).all()
    for m in mappings:
        vendor = m.vendor
        if vendor:
            vendor.supplier_types = supplier.supplier_types
            vendor.nature_of_service = supplier.nature_of_service
            vendor.service_description = supplier.service_description
    # caller must commit


def auto_create_or_link_supplier(vendor):
    """
    Called after vendor create/update.
    If vendor has no linked supplier, auto-create one from vendor data and link it.
    """
    if vendor.supplier_id:
        return  # already linked

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
    # caller must commit
