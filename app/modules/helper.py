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

def get_category_by_head_under(data):
    headUnder = data.get("headUnder")

    if not headUnder:
        return res("headUnder is required", [], 400)

    categories = CategoryMaster.query.filter(
        CategoryMaster.head_under.ilike(headUnder)
    ).all()

    data = [{
        "categoryId": category.id,
        "categoryName": category.category_name
    } for category in categories]

    return res(
        "Category list fetched successfully",
        data,
        200
    )

def get_cc_code_list(data):
    categoryId = data.get("categoryId")
    search = data.get("search", "").strip()

    if not categoryId:
        return res("categoryId is required", [], 400)

    query = CCCode.query.filter_by(
        category_id=categoryId
    )

    if search:
        query = query.filter(
            db.or_(
                CCCode.cc_code.ilike(f"%{search}%"),
                CCCode.cc_name.ilike(f"%{search}%")
            )
        )

    ccCodes = query.all()

    data = [{
        "ccCodeId": cc.id,
        "ccCode": cc.cc_code,
        "ccName": cc.cc_name
    } for cc in ccCodes]

    return res(
        "CC code list fetched successfully",
        data,
        200
    )