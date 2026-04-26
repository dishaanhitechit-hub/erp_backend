# modules/vendor/service.py
# Service layer for Vendor Master
import os
import uuid
from flask import g
from app.response import res
from app.models.vendor import Vendor
from app.models.item import Item
from app.models.cc_code import *
from app.models.category_group import *
from app.extensions import db



UPLOAD_FOLDER = "/uploads/vendor"


# ==========================================
# CREATE VENDOR
# ==========================================




def create_vendor(request):
    data = request.form
    files = request.files

    existing = Vendor.query.filter_by(
        ledger_code=data.get("ledgerCode")
    ).first()

    if existing:
        return res("Ledger Code already exists", [], 400)

    vendor = Vendor(
        ledger_code=data.get("ledgerCode"),
        ledger_name=data.get("ledgerName"),
        registered_address=data.get("registeredAddress"),
        corporate_address=data.get("corporateAddress"),

        category_id=data.get("categoryId"),

        pan=data.get("pan"),
        gstin=data.get("gstin"),
        state_code=data.get("stateCode"),
        state_name=data.get("stateName"),

        primary_contact_person=data.get("primaryContactPerson"),
        primary_contact_number=data.get("primaryContactNumber"),
        designation=data.get("designation"),
        whatsapp_number=data.get("whatsappNumber"),

        bank_account_number=data.get("bankAccountNumber"),
        bank_name=data.get("bankName"),
        branch_name=data.get("branchName"),
        ifsc_code=data.get("ifscCode"),
    )

    if hasattr(g, "current_user"):
        vendor.created_by = g.current_user.get("id")
    else:
        vendor.created_by = None

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    tradeFile = files.get("tradeLicenceFile")
    if tradeFile:
        ext = tradeFile.filename.split(".")[-1]
        filename = f"trade_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        tradeFile.save(filepath)
        vendor.trade_licence_file = filename

    panFile = files.get("panFile")
    if panFile:
        ext = panFile.filename.split(".")[-1]
        filename = f"pan_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        panFile.save(filepath)
        vendor.pan_file = filename

    gstnFile = files.get("gstnFile")
    if gstnFile:
        ext = gstnFile.filename.split(".")[-1]
        filename = f"gstn_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        gstnFile.save(filepath)
        vendor.gstn_file = filename

    bankFile = files.get("bankDetailsFile")
    if bankFile:
        ext = bankFile.filename.split(".")[-1]
        filename = f"bank_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        bankFile.save(filepath)
        vendor.bank_details_file = filename

    db.session.add(vendor)
    db.session.commit()

    baseUrl = request.host_url

    responseData = [{
        "vendorId": vendor.id,
        "ledgerCode": vendor.ledger_code,
        "ledgerName": vendor.ledger_name,

        "tradeLicenceUrl":
            f"{baseUrl}vendor/uploads/{vendor.trade_licence_file}"
            if vendor.trade_licence_file else None,

        "panUrl":
            f"{baseUrl}vendor/uploads/{vendor.pan_file}"
            if vendor.pan_file else None,

        "gstnUrl":
            f"{baseUrl}vendor/uploads/{vendor.gstn_file}"
            if vendor.gstn_file else None,

        "bankDetailsUrl":
            f"{baseUrl}vendor/uploads/{vendor.bank_details_file}"
            if vendor.bank_details_file else None
    }]

    return res("Vendor created successfully", responseData, 201)


def get_all_vendors():
    vendors = Vendor.query.order_by(Vendor.id.desc()).all()

    data = []

    for vendor in vendors:
        data.append({
            "vendorId": vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "vendorCategory": (
                vendor.vendor_category.category_name
                if vendor.vendor_category else None
            ),
            "status": vendor.status,
            "createdAt": vendor.created_at
        })

    return res("Vendor list fetched successfully", data, 200)


def get_vendor_by_id(vendorId):
    vendor = Vendor.query.get(vendorId)

    if not vendor:
        return res("Vendor not found", [], 404)

    data = [{
        "vendorId": vendor.id,
        "ledgerCode": vendor.ledger_code,
        "ledgerName": vendor.ledger_name,
        "registeredAddress": vendor.registered_address,
        "corporateAddress": vendor.corporate_address,

        "vendorCategory": (
            vendor.vendor_category.category_name
            if vendor.vendor_category else None
        ),

        "pan": vendor.pan,
        "gstin": vendor.gstin,
        "stateCode": vendor.state_code,
        "stateName": vendor.state_name,

        "primaryContactPerson": vendor.primary_contact_person,
        "primaryContactNumber": vendor.primary_contact_number,
        "designation": vendor.designation,
        "whatsappNumber": vendor.whatsapp_number,

        "bankAccountNumber": vendor.bank_account_number,
        "bankName": vendor.bank_name,
        "branchName": vendor.branch_name,
        "ifscCode": vendor.ifsc_code,

        "tradeLicenceFile": vendor.trade_licence_file,
        "panFile": vendor.pan_file,
        "gstnFile": vendor.gstn_file,
        "bankDetailsFile": vendor.bank_details_file,

        "status": vendor.status,
        "createdAt": vendor.created_at
    }]

    return res("Vendor fetched successfully", data, 200)

# UPDATE VENDOR


def update_vendor(vendorId, request):
    """
    Update vendor with file update support
    """

    data = request.form
    files = request.files

    vendor = Vendor.query.get(vendorId)

    if not vendor:
        return res("Vendor not found", [], 404)

    vendor.ledger_name = data.get("ledgerName", vendor.ledger_name)
    vendor.registered_address = data.get("registeredAddress", vendor.registered_address)
    vendor.corporate_address = data.get("corporateAddress", vendor.corporate_address)
    vendor.category_id = data.get("categoryId", vendor.category_id)

    vendor.pan = data.get("pan", vendor.pan)
    vendor.gstin = data.get("gstin", vendor.gstin)
    vendor.state_code = data.get("stateCode", vendor.state_code)
    vendor.state_name = data.get("stateName", vendor.state_name)

    vendor.primary_contact_person = data.get("primaryContactPerson", vendor.primary_contact_person)
    vendor.primary_contact_number = data.get("primaryContactNumber", vendor.primary_contact_number)
    vendor.designation = data.get("designation", vendor.designation)
    vendor.whatsapp_number = data.get("whatsappNumber", vendor.whatsapp_number)

    vendor.bank_account_number = data.get("bankAccountNumber", vendor.bank_account_number)
    vendor.bank_name = data.get("bankName", vendor.bank_name)
    vendor.branch_name = data.get("branchName", vendor.branch_name)
    vendor.ifsc_code = data.get("ifscCode", vendor.ifsc_code)

    # --------------------------------------
    # File Update
    # --------------------------------------

    tradeFile = files.get("tradeLicenceFile")
    if tradeFile:
        ext = tradeFile.filename.split(".")[-1]
        filename = f"trade_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        tradeFile.save(filepath)
        vendor.trade_licence_file = filename

    panFile = files.get("panFile")
    if panFile:
        ext = panFile.filename.split(".")[-1]
        filename = f"pan_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        panFile.save(filepath)
        vendor.pan_file = filename

    gstnFile = files.get("gstnFile")
    if gstnFile:
        ext = gstnFile.filename.split(".")[-1]
        filename = f"gstn_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        gstnFile.save(filepath)
        vendor.gstn_file = filename

    bankFile = files.get("bankDetailsFile")
    if bankFile:
        ext = bankFile.filename.split(".")[-1]
        filename = f"bank_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        bankFile.save(filepath)
        vendor.bank_details_file = filename

    db.session.commit()

    return res(
        "Vendor updated successfully",
        [{
            "vendorId": vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name
        }],
        200
    )

# ==========================================
# DELETE VENDOR
# ==========================================




def delete_vendor(vendorId):
    vendor = Vendor.query.get(vendorId)

    if not vendor:
        return res("Vendor not found", [], 404)

    db.session.delete(vendor)
    db.session.commit()

    return res("Vendor deleted successfully", [], 200)


def create_item(data, createdBy=None):
    existing = Item.query.filter_by(
        item_code=data.get("itemCode")
    ).first()

    if existing:
        return res("Item Code already exists", [], 400)

    item = Item(
        item_code=data.get("itemCode"),
        category_id=data.get("categoryId"),
        cc_code_id=data.get("ccCodeId"),
        item_name=data.get("itemName"),
        item_description=data.get("itemDescription"),
        unit=data.get("unit"),
        hsn_sac=data.get("hsnSac"),
        gst_percentage=data.get("gstPercentage"),
        created_by=createdBy
    )

    db.session.add(item)
    db.session.commit()

    return res(
        "Item created successfully",
        [{
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name
        }],
        201
    )


def get_all_items():
    items = Item.query.order_by(Item.id.desc()).all()

    data = []

    for item in items:
        data.append({
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name,
            "status": item.status
        })

    return res("Item list fetched successfully", data, 200)


def get_item_by_id(itemId):
    item = Item.query.get(itemId)

    if not item:
        return res("Item not found", [], 404)

    data = [{
        "itemId": item.id,
        "itemCode": item.item_code,
        "itemName": item.item_name,
        "itemDescription": item.item_description,
        "unit": item.unit,
        "hsnSac": item.hsn_sac,
        "gstPercentage": item.gst_percentage
    }]

    return res("Item fetched successfully", data, 200)


def update_item(itemId, data):
    item = Item.query.get(itemId)

    if not item:
        return res("Item not found", [], 404)

    item.category_id = data.get("categoryId", item.category_id)
    item.cc_code_id = data.get("ccCodeId", item.cc_code_id)
    item.item_name = data.get("itemName", item.item_name)
    item.item_description = data.get("itemDescription", item.item_description)
    item.unit = data.get("unit", item.unit)
    item.hsn_sac = data.get("hsnSac", item.hsn_sac)
    item.gst_percentage = data.get("gstPercentage", item.gst_percentage)

    db.session.commit()

    return res(
        "Item updated successfully",
        [{
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name
        }],
        200
    )


def delete_item(itemId):
    item = Item.query.get(itemId)

    if not item:
        return res("Item not found", [], 404)

    db.session.delete(item)
    db.session.commit()

    return res("Item deleted successfully", [], 200)


def create_cc_code(data, createdBy=None):
    existing = CCCode.query.filter_by(
        cc_code=data.get("ccCode")
    ).first()

    if existing:
        return res("CC Code already exists", [], 400)

    ccCode = CCCode(
        cc_code=data.get("ccCode"),
        cc_name=data.get("ccName"),
        group_id=data.get("groupId"),
        category_id=data.get("categoryId"),
        created_by=createdBy
    )

    db.session.add(ccCode)
    db.session.commit()

    return res(
        "CC Code created successfully",
        [{
            "ccId": ccCode.id,
            "ccCode": ccCode.cc_code,
            "ccName": ccCode.cc_name
        }],
        201
    )


def get_all_cc_codes():
    ccCodes = CCCode.query.order_by(CCCode.id.desc()).all()

    data = []

    for cc in ccCodes:
        data.append({
            "ccId": cc.id,
            "ccCode": cc.cc_code,
            "ccName": cc.cc_name
        })

    return res("CC Code list fetched successfully", data, 200)


def get_cc_code_by_id(ccId):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    data = [{
        "ccId": cc.id,
        "ccCode": cc.cc_code,
        "ccName": cc.cc_name
    }]

    return res("CC Code fetched successfully", data, 200)


def update_cc_code(ccId, data):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    cc.cc_name = data.get("ccName", cc.cc_name)
    cc.group_id = data.get("groupId", cc.group_id)
    cc.category_id = data.get("categoryId", cc.category_id)

    db.session.commit()

    return res(
        "CC Code updated successfully",
        [{
            "ccId": cc.id,
            "ccCode": cc.cc_code,
            "ccName": cc.cc_name
        }],
        200
    )


def delete_cc_code(ccId):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    db.session.delete(cc)
    db.session.commit()

    return res("CC Code deleted successfully", [], 200)

def create_group(data):
    existing = GroupMaster.query.filter_by(
        group_name=data.get("groupName")
    ).first()

    if existing:
        return res("Group already exists", [], 400)
    if hasattr(g, "current_user"):
        createdBy = g.current_user.get("id")
    else:
        createdBy = None
    group = GroupMaster(
        group_name=data.get("groupName"),
        head_under=data.get("headUnder"),
        created_by=createdBy
    )

    db.session.add(group)
    db.session.commit()

    return res(
        "Group created successfully",
        [{
            "groupId": group.id,
            "groupName": group.group_name,
            "headUnder": group.head_under
        }],
        200
    )



# CREATE CATEGORY


def create_category(data):
    existing = CategoryMaster.query.filter_by(
        category_name=data.get("categoryName")
    ).first()

    if existing:
        return res("Category already exists", [], 400)
    if hasattr(g, "current_user"):
        createdBy = g.current_user.get("id")
    category = CategoryMaster(
        category_name=data.get("categoryName"),
        head_under=data.get("headUnder"),
        created_by=createdBy
    )

    db.session.add(category)
    db.session.commit()

    return res(
        "Category created successfully",
        [{
            "categoryId": category.id,
            "categoryName": category.category_name,
            "headUnder": category.head_under
        }],
        201
    )

def update_group(groupId, data):
    group = GroupMaster.query.get(groupId)

    if not group:
        return res("Group not found", [], 404)

    group.group_name = data.get("groupName", group.group_name)
    group.head_under = data.get("headUnder", group.head_under)

    db.session.commit()

    return res(
        "Group updated successfully",
        [{
            "groupId": group.id,
            "groupName": group.group_name,
            "headUnder": group.head_under
        }],
        200
    )


# UPDATE CATEGORY


def update_category(categoryId, data):
    category = CategoryMaster.query.get(categoryId)

    if not category:
        return res("Category not found", [], 404)

    category.category_name = data.get("categoryName", category.category_name)
    category.head_under = data.get("headUnder", category.head_under)

    db.session.commit()

    return res(
        "Category updated successfully",
        [{
            "categoryId": category.id,
            "categoryName": category.category_name,
            "headUnder": category.head_under
        }],
        200
    )


# GET ALL GROUPS


def get_all_groups():
    groups = GroupMaster.query.order_by(
        GroupMaster.id.desc()
    ).all()

    data = []

    for group in groups:
        data.append({
            "groupId": group.id,
            "groupName": group.group_name,
            "headUnder": group.head_under,
            "status": group.status
        })

    return res(
        "Group list fetched successfully",
        data,
        200
    )



# GET ALL CATEGORIES


def get_all_categories():
    categories = CategoryMaster.query.order_by(
        CategoryMaster.id.desc()
    ).all()

    data = []

    for category in categories:
        data.append({
            "categoryId": category.id,
            "categoryName": category.category_name,
            "headUnder": category.head_under,
            "status": category.status
        })

    return res(
        "Category list fetched successfully",
        data,
        200
    )