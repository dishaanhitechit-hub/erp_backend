# modules/vendor/service.py
# Service layer for Vendor Master
import os
import uuid
import json
from flask import g
# from pandas.io.pytables import Term

from app.response import res
from app.models.vendor import Vendor
from app.models.item import Item
from app.models.asset import *
from app.models.cc_code import *
from app.models.unit import *
from app.models.category_group import *
from app.models.term_conditions import *
from app.extensions import db
from app.cloudinary_uploader import *
from app.modules.helper import get_category_by_head_under,get_cc_code_list
from app.modules.master.supplier_service import sync_vendor_to_suppliers, auto_create_or_link_supplier



# Vendor Code generator
def generate_ledger_code():
    last_vendor = Vendor.query.order_by(
        Vendor.id.desc()
    ).first()

    if not last_vendor:
        return "260001"

    try:
        last_number = int(
            last_vendor.ledger_code
        )
    except:
        last_number = 260000

    new_number = last_number + 1

    return str(new_number)

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

def generate_asset_code():
    last_asset = Asset.query.order_by(
        Asset.id.desc()
    ).first()

    if not last_asset:
        return "001"

    try:
        last_number = int(last_asset.asset_code)
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

        category_code=data.get("categoryId"),

        pan=data.get("pan"),
        gstin=data.get("gstin"),
        state_code=data.get("stateCode"),
        state_name=data.get("stateName"),

        primary_contact_person=data.get("primaryContactPerson"),
        primary_contact_number=data.get("primaryContactNumber"),
        designation=data.get("designation"),
        whatsapp_number=data.get("whatsappNumber"),
        email=data.get("email"),

        bank_account_number=data.get("bankAccountNumber"),
        bank_name=data.get("bankName"),
        branch_name=data.get("branchName"),
        ifsc_code=data.get("ifscCode"),

        supplier_types=(
            request.form.getlist("supplierTypes[]") or
            request.form.getlist("supplierTypes") or
            json.loads(data.get("supplierTypes", "[]") or "[]")
        ),
        nature_of_service=(
            request.form.getlist("natureOfService[]") or
            request.form.getlist("natureOfService") or
            json.loads(data.get("natureOfService", "[]") or "[]")
        ),
        service_description=data.get("serviceDescription"),
    )

    if hasattr(g, "current_user"):
        vendor.created_by = g.current_user.get("id")
    else:
        vendor.created_by = None



    tradeFile = files.get("tradeLicenceFile")
    vendor.trade_licence_file = upload_file_to_bunny(
        file=tradeFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="trade_licence"
    )

    panFile = files.get("panFile")
    vendor.pan_file = upload_file_to_bunny(
        file=panFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="pan"
    )

    gstnFile = files.get("gstnFile")
    vendor.gstn_file = upload_file_to_bunny(
        file=gstnFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="gstn"
    )

    bankFile = files.get("bankDetailsFile")
    vendor.bank_details_file = upload_file_to_bunny(
        file=bankFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="bank_details"
    )

    db.session.add(vendor)
    db.session.flush()

    existing_supplier_id = data.get("supplierId")
    auto_create_or_link_supplier(vendor, int(existing_supplier_id) if existing_supplier_id else None)
    db.session.commit()

    data = [{
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

    return res("ledger  created successfully", data, 201)


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
        "categoryId": vendor.category_code,
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

        "email": vendor.email,
        "supplierId": vendor.supplier_id,
        "supplierTypes": vendor.supplier_types or [],
        "natureOfService": vendor.nature_of_service or [],
        "serviceDescription": vendor.service_description,

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
        "categoryId": vendor.category_code,
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

        "email": vendor.email,
        "supplierId": vendor.supplier_id,
        "supplierTypes": vendor.supplier_types or [],
        "natureOfService": vendor.nature_of_service or [],
        "serviceDescription": vendor.service_description,

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
    vendor.category_code = data.get("categoryId", vendor.category_code)

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

    vendor.email = data.get("email", vendor.email)

    supplier_types_list = (
        request.form.getlist("supplierTypes[]") or
        request.form.getlist("supplierTypes")
    )
    if supplier_types_list:
        vendor.supplier_types = supplier_types_list
    elif "supplierTypes" in data:
        vendor.supplier_types = json.loads(data.get("supplierTypes") or "[]")
    nature_of_service_list = (
        request.form.getlist("natureOfService[]") or
        request.form.getlist("natureOfService")
    )
    if nature_of_service_list:
        vendor.nature_of_service = nature_of_service_list
    elif "natureOfService" in data:
        vendor.nature_of_service = json.loads(data.get("natureOfService") or "[]")
    vendor.service_description = data.get("serviceDescription", vendor.service_description)

    # --------------------------------------
    # File Update
    # --------------------------------------

    tradeFile = files.get("tradeLicenceFile")
    if tradeFile:
        vendor.trade_licence_file = upload_file_to_bunny(
        file=tradeFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="trade_licence"
    )

    panFile = files.get("panFile")
    if panFile:
        vendor.pan_file = upload_file_to_bunny(
        file=panFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="pan"
    )

    gstnFile = files.get("gstnFile")
    if gstnFile:
        vendor.gstn_file = upload_file_to_bunny(
        file=gstnFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="gstn"
    )

    bankFile = files.get("bankDetailsFile")
    if bankFile:
        vendor.bank_details_file = upload_file_to_bunny(
        file=bankFile,
        mainFolder="ledger",
        subFolder=vendor.ledger_code,
        fileName="bank_details"
    )

    sync_vendor_to_suppliers(vendor)
    auto_create_or_link_supplier(vendor)
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

    # Normal Create Item Flow


    item = Item(
        item_code=generate_item_code(),
        category_code=data.get("itemCategoryId"),
        cc_code_id=data.get("ccCodeId"),
        item_name=data.get("itemName"),
        item_description=data.get("itemDescription"),
        unit_id=data.get("unit"),
        hsn_sac=data.get("hsnSac"),
        gst_percentage=data.get("gstPercentage"),
    )

    if hasattr(g, "current_user"):
        item.created_by = g.current_user.get("id")
    else:
        item.created_by = None

    try:
        db.session.add(item)
        db.session.commit()
        db.session.refresh(item)
        return res(
            "Item created successfully",
            [{
                "itemId": item.id,
                "itemCode": item.item_code,
                "itemName": item.item_name,
                "ccCodeId": item.cc_code_id,
                "itemDisplayCode": (
                    f"{item.cc_code.cc_code}{item.item_code}"
                    if item.cc_code else None
                )
            }],
            201
        )

    except Exception:
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
            "itemCategoryId": item.category_code,
            "ccName": (
                item.cc_code.cc_name
                if item.cc_code else None
            ),


            "status": item.status,
            "hsnSac": item.hsn_sac,
            "gstPercentage": item.gst_percentage,
            "itemCategoryName": item.category.category_name,
            "itemDisplayCode": f"{item.cc_code.cc_code}{item.item_code}" if item.cc_code else None
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
        "unit": item.unit_id,
        "ccName": (
            item.cc_code.cc_name
            if item.cc_code else None
        ),
        "itemCategoryId": item.category_code,
        "ccCodeId": item.cc_code_id,
        "hsnSac": item.hsn_sac,
        "gstPercentage": item.gst_percentage,
        "itemCategoryName": item.category.category_name,
        "itemDisplayCode": f"{item.cc_code.cc_code}{item.item_code}" if item.cc_code else None
    }]

    return res("Item fetched successfully", data, 200)


def update_item(itemId, data):


    item = Item.query.get(itemId)

    if not item:
        return res("Item not found", [], 404)

    item.category_code = data.get("itemCategoryId", item.category_code)
    item.cc_code_id = data.get("ccCodeId", item.cc_code_id)
    item.item_name = data.get("itemName", item.item_name)
    item.item_description = data.get("itemDescription", item.item_description)
    item.unit_id = data.get("unit", item.unit_id)
    item.hsn_sac = data.get("hsnSac", item.hsn_sac)
    item.gst_percentage = data.get("gstPercentage", item.gst_percentage)

    db.session.commit()

    return res(
        "Item updated successfully",
        [{
            "itemId": item.id,
            "itemCode": item.item_code,
            "itemName": item.item_name,
            "itemDisplayCode": f"{item.cc_code.cc_code}{item.item_code}" if item.cc_code else None
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

    # category = CategoryMaster.query.filter_by(
    #     fixed_code=data.get("categoryFixedCode")
    # ).first()
    #
    # if not category:
    #     return res("Invalid Category Fixed Code", [], 400)

    ccCode = CCCode(
        cc_code=data.get("ccCode"),
        cc_name=data.get("ccName"),
        group_id=data.get("groupId"),
        category_code=data.get("categoryId"),
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
        # "ccCategoryId": ccCode.category_id,
        "ccCategoryName": ccCode.category.category_name,
        "ccCategoryId": ccCode.category_code,
        "ccGroupName": ccCode.group.group_name
        }]

        return res("CC Code created successfully",data,201)
    except Exception as e :
        db.session.rollback()
        print(e)
        return res("Something went wrong", [], 500)

def get_all_cc_codes(data):

    categoryCode = data.get("categoryId")
    search = data.get("search", "").strip()
    key = data.get("key")

    query = CCCode.query

    # -------------------------
    # category filter (always)
    # -------------------------

    if categoryCode:
        query = query.filter(
            CCCode.category_code == categoryCode
        )

    # -------------------------
    # extra filter
    # -------------------------

    if key == "asset":

        query = (
            query
            .join(GroupMaster)
            .filter(
                GroupMaster.group_name=="Fixed Asset"
            )
        )


    elif key == "item":

        query = (
            query
            .join(GroupMaster)
            .filter(
                GroupMaster.group_name.in_([
                    "Direct Expenses",
                    "Indirect Expenses"
                ])
            )
        )


    # -------------------------
    # search
    # -------------------------

    if search:

        query=query.filter(

            db.or_(

                CCCode.cc_code.ilike(
                    f"%{search}%"
                ),

                CCCode.cc_name.ilike(
                    f"%{search}%"
                )

            )
        )


    ccCodes=query.order_by(
        CCCode.id.desc()
    ).all()


    data=[]

    for cc in ccCodes:

        data.append({

            "ccId":cc.id,
            "ccCode":cc.cc_code,
            "ccName":cc.cc_name,

            "ccGroupId":cc.group_id,

            "ccCategoryId":cc.category_code,

            "ccCategoryName":
            cc.category.category_name
            if cc.category else None,

            "ccGroupName":
            cc.group.group_name
            if cc.group else None

        })

    return res(
        "CC Code list fetched successfully",
        data,
        200
    )

def get_cc_code_by_id(ccId):
    cc = CCCode.query.get(ccId)

    if not cc:
        return res("CC Code not found", [], 404)

    data = [{
        "ccId": cc.id,
        "ccCode": cc.cc_code,
        "ccName": cc.cc_name,
        "ccGroupId": cc.group_id,
        "ccCategoryId": cc.category_code,
        "ccCategoryFixedCode": cc.category.fixed_code,
        "ccCategoryName": cc.category.category_name if cc.category else None,
        "ccGroupName": cc.group.group_name if cc.group else None
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
    cc.category_code = data.get("categoryId", cc.category_code)
    cc.cc_code = newCcCode
    try:
        db.session.commit()
        data=[{
        "ccId": cc.id,
        "ccCode": cc.cc_code ,
        "ccName": cc.cc_name,
        "ccGroupId": cc.group_id,
        "ccCategoryId": cc.category_code,
        "ccCategoryName": cc.category.category_name if cc.category else None,
        "ccGroupName": cc.group.group_name if cc.group else None}]
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
    else:
        createdBy = None

    category = CategoryMaster(
        fixed_code=data.get("categoryCode"),
        category_name=data.get("categoryName"),
        created_by=createdBy
    )

    try:
        db.session.add(category)
        db.session.commit()

        return res(
            "Category created successfully",
            [{
                "categoryId": category.id,
                "categoryCode": category.fixed_code,
                "categoryName": category.category_name
            }],
            201
        )

    except Exception:
        db.session.rollback()
        return res(
            "Failed to create category",
            [],
            500
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

    category.fixed_code = data.get(
        "categoryCode",
        category.fixed_code
    )

    category.category_name = data.get(
        "categoryName",
        category.category_name
    )

    try:
        db.session.commit()

        return res(
            "Category updated successfully",
            [{
                "categoryId": category.id,
                "categoryCode": category.fixed_code,
                "categoryName": category.category_name
            }],
            200
        )

    except Exception:
        db.session.rollback()

        return res(
            "Failed to update category",
            [],
            500
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


def get_all_categories(data):

    categories = CategoryMaster.query.order_by(
        CategoryMaster.id.desc()
    ).all()

    data = []

    for category in categories:
        data.append({
            "categoryId": category.id,
            "categoryCode": category.fixed_code,
            "categoryName": category.category_name,
            "status": category.status
        })

    return res(
        "Category list fetched successfully",
        data,
        200
    )

# same code for Asset:
# Item -> Asset
# item -> asset
# item_code -> asset_code
# item_name -> asset_name
# item_description -> asset_description
# itemDisplayCode -> assetDisplayCode

def create_asset(data):


    asset = Asset(
        asset_code=generate_asset_code(),
        category_code=data.get("itemCategoryId"),
        cc_code_id=data.get("ccCodeId"),
        asset_name=data.get("assetName"),
        asset_description=data.get("assetDescription"),
        unit_id=data.get("unit"),
        hsn_sac=data.get("hsnSac"),
        gst_percentage=data.get("gstPercentage"),
    )

    if hasattr(g, "current_user"):
        asset.created_by = g.current_user.get("id")
    else:
        asset.created_by = None

    try:
        db.session.add(asset)
        db.session.commit()

        return res(
            "Asset created successfully",
            [{
                "assetId": asset.id,
                "assetCode": asset.asset_code,
                "assetName": asset.asset_name,
                "ccCodeId": asset.cc_code_id,
                "assetDisplayCode": (
                    f"{asset.cc_code.cc_code}{asset.asset_code}"
                    if asset.cc_code else None
                )
            }],
            201
        )

    except Exception:
        db.session.rollback()
        return res("Failed to create asset", [], 500)


def get_all_assets():
    assets = Asset.query.order_by(Asset.id.desc()).all()

    data = []

    for asset in assets:
        data.append({
            "assetId": asset.id,
            "assetCode": asset.asset_code,
            "assetName": asset.asset_name,
            "assetDescription": asset.asset_description,
            "itemCategoryId": asset.category_code,
            "ccName": (
                asset.cc_code.cc_name
                if asset.cc_code else None
            ),
            "status": asset.status,
            "hsnSac": asset.hsn_sac,
            "gstPercentage": asset.gst_percentage,
            "assetCategoryName": asset.category.category_name,
            "assetDisplayCode": (
                f"{asset.cc_code.cc_code}{asset.asset_code}"
                if asset.cc_code else None
            )
        })

    return res("Asset list fetched successfully", data, 200)


def get_asset_by_id(assetId):
    asset = Asset.query.get(assetId)

    if not asset:
        return res("Asset not found", [], 404)

    data = [{
        "assetId": asset.id,
        "assetCode": asset.asset_code,
        "assetName": asset.asset_name,
        "assetDescription": asset.asset_description,
        "unit": asset.unit_id,
        "ccName": (
            asset.cc_code.cc_name
            if asset.cc_code else None
        ),
        "itemCategoryId": asset.category_code,
        "ccCodeId": asset.cc_code_id,
        "hsnSac": asset.hsn_sac,
        "gstPercentage": asset.gst_percentage,
        "assetCategoryName": asset.category.category_name,
        "assetDisplayCode": (
            f"{asset.cc_code.cc_code}{asset.asset_code}"
            if asset.cc_code else None
        )
    }]

    return res("Asset fetched successfully", data, 200)


def update_asset(assetId, data):


    asset = Asset.query.get(assetId)

    if not asset:
        return res("Asset not found", [], 404)

    asset.category_code = data.get("itemCategoryId", asset.category_code)
    asset.cc_code_id = data.get("ccCodeId", asset.cc_code_id)
    asset.asset_name = data.get("assetName", asset.asset_name)
    asset.asset_description = data.get("assetDescription", asset.asset_description)
    asset.unit_id = data.get("unit", asset.unit_id)
    asset.hsn_sac = data.get("hsnSac", asset.hsn_sac)
    asset.gst_percentage = data.get("gstPercentage", asset.gst_percentage)

    db.session.commit()

    return res(
        "Asset updated successfully",
        [{
            "assetId": asset.id,
            "assetCode": asset.asset_code,
            "assetName": asset.asset_name,
            "assetDisplayCode": (
                f"{asset.cc_code.cc_code}{asset.asset_code}"
                if asset.cc_code else None
            )
        }],
        200
    )


def delete_asset(assetId):
    asset = Asset.query.get(assetId)

    if not asset:
        return res("Asset not found", [], 404)

    db.session.delete(asset)
    db.session.commit()

    return res("Asset deleted successfully", [], 200)

# service.py

def create_unit(data):
    unitType = data.get("unitType")

    unit = Unit(
        unit_name=data.get("unitName"),
        short_name=data.get("shortName"),
        unit_type=unitType,

        # only for Child unit
        parent_unit_id=(
            data.get("parentUnitId")
            if unitType == "Child" else None
        ),


        parent_unit_multiply_factor=(
            data.get("parentUnitMultiplyFactor")
            if unitType == "Child" else None
        ),

        # category fixed_code
        category_code=data.get("categoryId")
    )
    if unitType == "Child":
        if not data.get("parentUnitId"):
            return res(
                "Parent Unit required for Child type",
                [],
                400
            )
    if hasattr(g, "current_user"):
        unit.created_by = g.current_user.get("id")
    else:
        unit.created_by = None

    db.session.add(unit)
    db.session.commit()

    return res(
        "Unit created successfully",
        [{
            "unitId": unit.id,
            "unitName": unit.unit_name,
            "shortName": unit.short_name,
            "unitType": unit.unit_type,
            "categoryId": unit.category_code,
            "categoryName": unit.category.category_name
        }],
        201
    )


def get_all_units(filters=None):

    query = Unit.query

    if filters:

        # ==================================
        # FILTER BY UNIT TYPE
        # ==================================

        if filters.get("unitType"):

            query = query.filter(
                Unit.unit_type == filters.get("unitType")
            )

        # ==================================
        # FILTER BY CATEGORY
        # ==================================

        if filters.get("categoryId"):

            query = query.filter(
                Unit.category_code == filters.get("categoryId")
            )

    # ==================================
    # FINAL QUERY
    # ==================================

    units = query.order_by(
        Unit.id.desc()
    ).all()

    data = [{
        "unitId": unit.id,
        "unitName": unit.unit_name,
        "shortName": unit.short_name,
        "unitType": unit.unit_type,

        "parentUnitId": unit.parent_unit_id,

        "parentUnitName": (
            unit.parent_unit.unit_name
            if unit.parent_unit else None
        ),

        "parentUnitMultiplyFactor":
            unit.parent_unit_multiply_factor,

        "categoryId": unit.category_code,

        "categoryName":
            unit.category.category_name,

        "status": unit.status

    } for unit in units]

    return res(
        "Unit list fetched successfully",
        data,
        200
    )


def get_unit_by_id(unitId):
    unit = Unit.query.get(unitId)

    if not unit:
        return res("Unit not found", [], 404)

    return res(
        "Unit fetched successfully",
        [{
            "unitId": unit.id,
            "unitName": unit.unit_name,
            "shortName": unit.short_name,
            "unitType": unit.unit_type,

            "parentUnitId": unit.parent_unit_id,
            "parentUnitName": (
                unit.parent_unit.unit_name
                if unit.parent_unit else None
            ),

            "parentUnitMultiplyFactor": unit.parent_unit_multiply_factor,

            "categoryId": unit.category_code,
            "categoryName": unit.category.category_name,

            "status": unit.status
        }],
        200
    )


def update_unit(unitId, data):
    unit = Unit.query.get(unitId)

    if not unit:
        return res("Unit not found", [], 404)

    unitType = data.get("unitType", unit.unit_type)

    unit.unit_name = data.get(
        "unitName",
        unit.unit_name
    )

    unit.short_name = data.get(
        "shortName",
        unit.short_name
    )

    unit.unit_type = unitType

    # only for Child
    unit.parent_unit_id = (
        data.get("parentUnitId")
        if unitType == "Child"
        else None
    )

    unit.parent_unit_multiply_factor = (
        data.get("parentUnitMultiplyFactor")
        if unitType == "Child"
        else None
    )

    unit.category_code = data.get(
        "categoryId",
        unit.category_code
    )

    db.session.commit()

    return res(
        "Unit updated successfully",
        [{
            "unitId": unit.id,
            "unitName": unit.unit_name,
            "categoryId": unit.category_code,
            "categoryName": unit.category.category_name
        }],
        200
    )


def delete_unit(unitId):
    unit = Unit.query.get(unitId)

    if not unit:
        return res("Unit not found", [], 404)

    db.session.delete(unit)
    db.session.commit()

    return res(
        "Unit deleted successfully",
        [],
        200
    )

# _____________________________

#       TERM_CONDITION

# ______________________________

from flask import request
from app.models.term import Term, TermGroup, TermPoint, VALID_MODULES, MODULE_SUBMODULE_MAP, VALID_TERM_TYPES, VALID_POINT_STYLES


def _validate_term_fields(data):
    module = data.get("module")
    sub_module = data.get("subModule")
    term_type = data.get("termType")

    if module not in VALID_MODULES:
        return res(
            f"Invalid module '{module}'. Allowed: {', '.join(VALID_MODULES)}",
            [], 400
        )

    allowed_sub = MODULE_SUBMODULE_MAP.get(module, [])
    if sub_module not in allowed_sub:
        return res(
            f"Invalid subModule '{sub_module}' for module '{module}'. Allowed: {', '.join(allowed_sub)}",
            [], 400
        )

    if term_type not in VALID_TERM_TYPES:
        return res(
            f"Invalid termType '{term_type}'. Allowed: {', '.join(VALID_TERM_TYPES)}",
            [], 400
        )

    for i, group in enumerate(data.get("termGroups", [])):
        ps = group.get("pointStyle")
        if ps not in VALID_POINT_STYLES:
            return res(
                f"Invalid pointStyle '{ps}' in termGroups[{i}]. Allowed: {', '.join(VALID_POINT_STYLES)}",
                [], 400
            )

    return None


def _serialize_term(term):
    return {
        "termId": term.term_id,
        "module": term.module,
        "subModule": term.sub_module,
        "termType": term.term_type,
        "termGroups": [
            {
                "groupId": g.group_id,
                "sortOrder": g.sort_order,
                "title": g.title,
                "description": g.description,
                "pointStyle": g.point_style,
                "points": [
                    {
                        "pointId": p.point_id,
                        "sortOrder": p.sort_order,
                        "text": p.text
                    }
                    for p in g.points
                ]
            }
            for g in term.term_groups
        ]
    }


def create_term(data):
    err = _validate_term_fields(data)
    if err:
        return err

    term = Term(
        module=data.get("module"),
        sub_module=data.get("subModule"),
        term_type=data.get("termType"),
    )
    db.session.add(term)
    db.session.flush()

    for g_data in data.get("termGroups", []):
        group = TermGroup(
            term_id=term.term_id,
            sort_order=g_data.get("sortOrder", 0),
            title=g_data.get("title"),
            description=g_data.get("description"),
            point_style=g_data.get("pointStyle"),
        )
        db.session.add(group)
        db.session.flush()

        for p_data in g_data.get("points", []):
            db.session.add(TermPoint(
                group_id=group.group_id,
                sort_order=p_data.get("sortOrder", 0),
                text=p_data.get("text"),
            ))

    db.session.commit()

    return res("Term created successfully", [{"termId": term.term_id}], 201)


def term_edit(termId, data):
    term = Term.query.get(termId)
    if not term:
        return res("Term not found", [], 404)

    err = _validate_term_fields(data)
    if err:
        return err

    term.module = data.get("module")
    term.sub_module = data.get("subModule")
    term.term_type = data.get("termType")

    for g in list(term.term_groups):
        db.session.delete(g)
    db.session.flush()

    for g_data in data.get("termGroups", []):
        group = TermGroup(
            term_id=term.term_id,
            sort_order=g_data.get("sortOrder", 0),
            title=g_data.get("title"),
            description=g_data.get("description"),
            point_style=g_data.get("pointStyle"),
        )
        db.session.add(group)
        db.session.flush()

        for p_data in g_data.get("points", []):
            db.session.add(TermPoint(
                group_id=group.group_id,
                sort_order=p_data.get("sortOrder", 0),
                text=p_data.get("text"),
            ))

    db.session.commit()

    return res("Term updated successfully", [], 200)


def get_all_terms():
    query = Term.query
    module = request.args.get("module")
    sub_module = request.args.get("subModule")
    if module:
        query = query.filter(Term.module == module)
    if sub_module:
        query = query.filter(Term.sub_module == sub_module)
    terms = query.order_by(Term.term_id.desc()).all()
    return res("All terms fetched successfully", [_serialize_term(t) for t in terms], 200)


def get_term_by_id(termId):
    term = Term.query.get(termId)
    if not term:
        return res("Term not found", [], 404)
    return res("Term fetched successfully", [_serialize_term(term)], 200)


def delete_term(termId):
    term = Term.query.get(termId)
    if not term:
        return res("Term not found", [], 404)
    db.session.delete(term)
    db.session.commit()
    return res("Term deleted successfully", [], 200)


# ==========================================
# BANK & CASH
# ==========================================

from app.models.bankCash import BankCash


def create_bank_cash(data):
    existing = BankCash.query.filter_by(
        bank_code=data.get("bankCode")
    ).first()

    if existing:
        return res("Bank Code already exists", [], 400)

    record = BankCash(
        type=data.get("type"),
        bank_code=data.get("bankCode"),
        bank_holder_name=data.get("bankHolderName"),
        bank_account_number=data.get("bankAcNumber"),
        bank_name=data.get("bankName"),
        branch_name=data.get("branchName"),
        ifsc_code=data.get("ifscCode"),
        micr_code=data.get("micrCode"),
        customer_id=data.get("customerId"),
        branch_manager_name=data.get("branchManagerName"),
        branch_manager_contact=data.get("branchManagerContact"),
        branch_manager_email=data.get("branchManagerMailId"),
    )

    if hasattr(g, "current_user"):
        record.created_by = g.current_user.get("id")

    db.session.add(record)
    db.session.commit()

    return res(
        "Bank/Cash created successfully",
        [{"id": record.id, "bankCode": record.bank_code, "type": record.type}],
        201
    )


def get_all_bank_cash():
    records = BankCash.query.order_by(BankCash.id.desc()).all()

    data = [{
        "id": r.id,
        "type": r.type,
        "bankCode": r.bank_code,
        "bankHolderName": r.bank_holder_name,
        "bankAcNumber": r.bank_account_number,
        "bankName": r.bank_name,
        "branchName": r.branch_name,
        "ifscCode": r.ifsc_code,
        "micrCode": r.micr_code,
        "customerId": r.customer_id,
        "branchManagerName": r.branch_manager_name,
        "branchManagerContact": r.branch_manager_contact,
        "branchManagerMailId": r.branch_manager_email,
        "status": r.status,
        "createdAt": r.created_at
    } for r in records]

    return res("Bank/Cash list fetched successfully", data, 200)


def get_bank_cash_by_id(record_id):
    r = BankCash.query.get(record_id)

    if not r:
        return res("Record not found", [], 404)

    return res(
        "Bank/Cash fetched successfully",
        [{
            "id": r.id,
            "type": r.type,
            "bankCode": r.bank_code,
            "bankHolderName": r.bank_holder_name,
            "bankAcNumber": r.bank_account_number,
            "bankName": r.bank_name,
            "branchName": r.branch_name,
            "ifscCode": r.ifsc_code,
            "micrCode": r.micr_code,
            "customerId": r.customer_id,
            "branchManagerName": r.branch_manager_name,
            "branchManagerContact": r.branch_manager_contact,
            "branchManagerMailId": r.branch_manager_email,
            "status": r.status
        }],
        200
    )


def update_bank_cash(record_id, data):
    r = BankCash.query.get(record_id)

    if not r:
        return res("Record not found", [], 404)

    r.type                   = data.get("type", r.type)
    r.bank_holder_name       = data.get("bankHolderName", r.bank_holder_name)
    r.bank_account_number    = data.get("bankAcNumber", r.bank_account_number)
    r.bank_name              = data.get("bankName", r.bank_name)
    r.branch_name            = data.get("branchName", r.branch_name)
    r.ifsc_code              = data.get("ifscCode", r.ifsc_code)
    r.micr_code              = data.get("micrCode", r.micr_code)
    r.customer_id            = data.get("customerId", r.customer_id)
    r.branch_manager_name    = data.get("branchManagerName", r.branch_manager_name)
    r.branch_manager_contact = data.get("branchManagerContact", r.branch_manager_contact)
    r.branch_manager_email   = data.get("branchManagerMailId", r.branch_manager_email)

    db.session.commit()

    return res(
        "Bank/Cash updated successfully",
        [{"id": r.id, "bankCode": r.bank_code, "type": r.type}],
        200
    )


def delete_bank_cash(record_id):
    r = BankCash.query.get(record_id)

    if not r:
        return res("Record not found", [], 404)

    db.session.delete(r)
    db.session.commit()

    return res("Bank/Cash deleted successfully", [], 200)