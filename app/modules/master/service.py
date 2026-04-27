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
from app.cloudinary_uploader import *



UPLOAD_FOLDER = "/uploads/vendor"


# Vendor Code generator
def generate_ledger_code():
    last_vendor = Vendor.query.order_by(
        Vendor.id.desc()
    ).first()

    if not last_vendor:
        return "3000001"

    last_code = last_vendor.ledger_code

    try:
        last_number = int(last_code[1:])
    except:
        last_number = 0

    new_number = last_number + 1

    return f"3{new_number:06d}"

def generate_item_code():
    last_item = Item.query.order_by(
        Item.id.desc()
    ).first()

    if not last_item:
        return "001"

    try:
        last_number = int(last_item.item_code)
    except:
        last_number = 0

    new_number = last_number + 1

    return f"{new_number:03d}"

# CREATE VENDOR
def create_vendor(request):
    data = request.form
    files = request.files

    vendor = Vendor(
        ledger_code=generate_ledger_code(),
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
    vendor.trade_licence_file = upload_file_to_cloudinary(
        file=tradeFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="trade_licence"
    )

    panFile = files.get("panFile")
    vendor.pan_file = upload_file_to_cloudinary(
        file=panFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="pan"
    )

    gstnFile = files.get("gstnFile")
    vendor.gstn_file = upload_file_to_cloudinary(
        file=gstnFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="gstn"
    )

    bankFile = files.get("bankDetailsFile")
    vendor.bank_details_file = upload_file_to_cloudinary(
        file=bankFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="bank_details"
    )

    db.session.add(vendor)
    db.session.commit()


    responseData = [{
        "ledgerId": vendor.id,
        "ledgerCode": vendor.ledger_code,
        "ledgerName": vendor.ledger_name,

        "tradeLicenceUrl": vendor.trade_licence_file,


        "panUrl":
            vendor.pan_file,


        "gstnUrl":
            vendor.gstn_file,


        "bankDetailsUrl":
            vendor.bank_details_file

    }]

    return res("ledger  created successfully", responseData, 201)


def get_all_vendors():
    vendors = Vendor.query.order_by(Vendor.id.desc()).all()

    data = []

    for vendor in vendors:
        data.append({
        "ledgerId": vendor.id,
        "ledgerCode": vendor.ledger_code,
        "ledgerName": vendor.ledger_name,
        "registeredAddress": vendor.registered_address,
        "corporateAddress": vendor.corporate_address,

        "categoryName": (
            vendor.vendor_category.category_name
            if vendor.vendor_category else None
        ),
        "categoryId": vendor.category_id,
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
        })

    return res("ledger  list fetched successfully", data, 200)


def get_vendor_by_id(ledgerId):
    vendor = Vendor.query.get(ledgerId)

    if not vendor:
        return res("ledger  not found", [], 404)

    data = [{
        "ledgerId": vendor.id,
        "ledgerCode": vendor.ledger_code,
        "ledgerName": vendor.ledger_name,
        "registeredAddress": vendor.registered_address,
        "corporateAddress": vendor.corporate_address,

        "categoryName": (
            vendor.vendor_category.category_name
            if vendor.vendor_category else None
        ),
        "categoryId": vendor.category_id,
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

    return res("ledger  fetched successfully", data, 200)

# UPDATE VENDOR


def update_vendor(vendorId, request):
    """
    Update vendor with file update support
    """

    data = request.form
    files = request.files

    vendor = Vendor.query.get(vendorId)

    if not vendor:
        return res("ledger  not found", [], 404)

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
        vendor.trade_licence_file = upload_file_to_cloudinary(
        file=tradeFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="trade_licence"
    )

    panFile = files.get("panFile")
    if panFile:
        vendor.pan_file = upload_file_to_cloudinary(
        file=panFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="pan"
    )

    gstnFile = files.get("gstnFile")
    if gstnFile:
        vendor.gstn_file = upload_file_to_cloudinary(
        file=gstnFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="gstn"
    )

    bankFile = files.get("bankDetailsFile")
    if bankFile:
        vendor.bank_details_file = upload_file_to_cloudinary(
        file=bankFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="bank_details"
    )

    db.session.commit()

    return res(
        "ledger updated successfully",
        [{
            "ledgerId": vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "tradeLicenceFile": vendor.trade_licence_file,
            "panFile": vendor.pan_file,
            "gstnFile": vendor.gstn_file,
            "bankDetailsFile": vendor.bank_details_file

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


def create_item(data):
    # existing = Item.query.filter_by(
    #     item_code=data.get("itemCode")
    # ).first()
    #
    # if existing:
    #     return res("Item Code already exists", [], 400)


    item = Item(
        item_code=generate_item_code(),
        category_id=data.get("itemCategoryId"),
        cc_code_id=data.get("ccCodeId"),
        item_name=data.get("itemName"),
        item_description=data.get("itemDescription"),
        unit=data.get("unit"),
        hsn_sac=data.get("hsnSac"),
        gst_percentage=data.get("gstPercentage"),
    )
    print(item)
    # db.session.add(item)
    # db.session.commit()
    if hasattr(g, "current_user"):
        item.created_by = g.current_user.get("id")
    else:
        item.created_by = None
    try:
        db.session.add(item)
        db.session.commit()

        return res(
        "Item created successfully",
        [{
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name,
            "ccCodeId": item.cc_code_id,

            "itemDisplayCode": f"{item.cc_code.cc_code}_{item.item_code}"if item.cc_code else None
        }],
        201
        )
    except Exception :
        db.session.rollback()
        return res("Failed to create item", [], 500)


def get_all_items():
    items = Item.query.order_by(Item.id.desc()).all()

    data = []

    for item in items:
        data.append({
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name,
            "itemDescription": item.item_description,
            "itemCategoryId": item.category_id,
            "ccName": (
                item.cc_code.cc_name
                if item.cc_code else None
            ),


            "status": item.status,
            "hsnSac": item.hsn_sac,
            "gstPercentage": item.gst_percentage,
            "itemCategoryName": item.category.category_name,
            "itemDisplayCode": f"{item.cc_code.cc_code}_{item.item_code}" if item.cc_code else None
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
        "ccName": (
            item.cc_code.cc_name
            if item.cc_code else None
        ),
        "itemCategoryId": item.category_id,
        "ccCodeId": item.cc_code_id,
        "hsnSac": item.hsn_sac,
        "gstPercentage": item.gst_percentage,
        "itemCategoryName": item.category.category_name,
        "itemDisplayCode": f"{item.cc_code.cc_code}_{item.item_code}" if item.cc_code else None
    }]

    return res("Item fetched successfully", data, 200)


def update_item(itemId, data):
    item = Item.query.get(itemId)

    if not item:
        return res("Item not found", [], 404)

    item.category_id = data.get("itemCategoryId", item.category_id)
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
            "itemName": item.item_name,
            "itemDisplayCode": f"{item.cc_code.cc_code}_{item.item_code}" if item.cc_code else None
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
    try:
        db.session.add(ccCode)
        db.session.commit()

        data = [{
        "ccId": ccCode.id,
        "ccCode": ccCode.cc_code,
        "ccName": ccCode.cc_name,
        "ccGroupId": ccCode.group_id,
        "ccCategoryId": ccCode.category_id,
        "ccCategoryName": ccCode.category.category_name,
        "ccGroupName": ccCode.group.group_name
        }]

        return res("CC Code created successfully",data,201)
    except Exception :
        db.session.rollback()
        return res("Something went wrong", [], 500)

def get_all_cc_codes():
    ccCodes = CCCode.query.order_by(CCCode.id.desc()).all()

    data = []

    for cc in ccCodes:
        data.append({
            "ccId": cc.id,
        "ccCode": cc.cc_code,
        "ccName": cc.cc_name,
        "ccGroupId": cc.group_id,
        "ccCategoryId": cc.category_id,
        "ccCategoryName": cc.category.category_name,
        "ccGroupName": cc.group.group_name
        })

    return res("CC Code list fetched successfully", data, 200)


def get_cc_code_by_id(ccId):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    data = [{
        "ccId": cc.id,
        "ccCode": cc.cc_code,
        "ccName": cc.cc_name,
        "ccGroupId": cc.group_id,
        "ccCategoryId": cc.category_id,
        "ccCategoryName": cc.category.category_name,
        "ccGroupName": cc.group.group_name
    }]

    return res("CC Code fetched successfully", data, 200)


def update_cc_code(ccId, data):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    newCcCode = data.get("ccCode", cc.cc_code)

    existing = CCCode.query.filter(
        CCCode.cc_code == newCcCode ,
        CCCode.id != ccId
    ).first()

    if existing:
        return res("CC Code already exists", [], 400)

    cc.cc_name = data.get("ccName", cc.cc_name)
    cc.group_id = data.get("groupId", cc.group_id)
    cc.category_id = data.get("categoryId", cc.category_id)
    cc.cc_code = newCcCode
    try:
        db.session.commit()
        data=[{
        "ccId": cc.id,
        "ccCode": cc.cc_code ,
        "ccName": cc.cc_name,
        "ccGroupId": cc.group_id,
        "ccCategoryId": cc.category_id,
        "ccCategoryName": cc.category.category_name,
        "ccGroupName": cc.group.group_name }]
        return res(
        "CC Code updated successfully",
        data,
        200
        )
    except Exception :
        db.session.rollback()
        return res("Something went wrong", [], 500)

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