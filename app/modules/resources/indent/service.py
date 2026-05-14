
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.response import res
from app.models.project import Project
from app.models.category_group import CategoryMaster
from app.models.item import Item

from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem



# GENERATE INDENT NUMBER


def generate_indent_no(project_code):

    today = datetime.now().strftime("%Y%m")

    last_indent = (
        IndentMaster.query
        .filter(
            IndentMaster.project_code == project_code
        )
        .order_by(IndentMaster.id.desc())
        .first()
    )

    if last_indent:
        try:
            last_serial = int(last_indent.indent_no.split("-")[-1])
        except:
            last_serial = 0
    else:
        last_serial = 0

    new_serial = str(last_serial + 1).zfill(4)

    return f"IND-{project_code}-{today}-{new_serial}"



# CREATE INDENT


def create_indent(data, created_by=None):

    try:

        project = Project.query.filter_by(
            project_code=data.get("projectCode")
        ).first()

        if not project:
            return res("Invalid project code", [], 400)

        # ==========================================
        # VALIDATE CATEGORY
        # ==========================================

        category = CategoryMaster.query.filter_by(
            fixed_code=data.get("categoryCode")
        ).first()

        if not category:
            return res("Invalid category code", [], 400)


        # VALIDATE ITEMS


        items = data.get("items", [])

        if not items:
            return res("Indent items required", [], 400)


        # CREATE MASTER


        indent = IndentMaster(
            indent_no=generate_indent_no(
                data.get("projectCode")
            ),

            project_code=data.get("projectCode"),

            category_code=data.get("categoryCode"),

            indent_date=datetime.utcnow(),

            priority=data.get("priority"),

            required_within=data.get("requiredWithin"),

            indent_placed_by=data.get("indentPlacedBy"),

            site_reg_serial_no=data.get("siteRegSerialNo"),

            sale_order_no=data.get("saleOrderNo"),

            remarks=data.get("remarks"),

            indent_status=data.get("status"),

            order_status="Pending",

            created_by=created_by
        )

        db.session.add(indent)
        db.session.flush()

        # ==========================================
        # CREATE ITEMS
        # ==========================================

        for row in items:

            item = Item.query.filter_by(
                item_code=row.get("itemCode")
            ).first()

            if not item:
                db.session.rollback()
                return res(
                    f"Invalid item code : {row.get('itemCode')}",
                    [],
                    400
                )

            # ======================================
            # CATEGORY MATCH VALIDATION
            # ======================================

            if item.category_code != data.get("categoryCode"):
                db.session.rollback()

                return res(
                    f"Item {item.item_code} "
                    f"does not belong to category "
                    f"{data.get('categoryCode')}",
                    [],
                    400
                )

            # ======================================
            # QTY VALIDATION
            # ======================================

            qty = row.get("qty")

            if not qty or float(qty) <= 0:
                db.session.rollback()

                return res(
                    f"Invalid qty for item "
                    f"{item.item_code}",
                    [],
                    400
                )

            indent_item = IndentItem(

                indent_id=indent.id,

                item_code=item.item_code,

                qty=qty,

                location=row.get("location"),

                note=row.get("note"),

                created_by=created_by
            )

            db.session.add(indent_item)

        # COMMIT


        db.session.commit()

        return res(
            "Indent created successfully",
            {
                "indentId": indent.id,
                "indentNo": indent.indent_no
            },
            201
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


# INDENT LIST


def get_indent_list(filters=None):

    try:

        query = IndentMaster.query

        if filters:

            if filters.get("projectCode"):
                query = query.filter(
                    IndentMaster.project_code ==
                    filters.get("projectCode")
                )

            if filters.get("status"):
                query = query.filter(
                    IndentMaster.indent_status ==
                    filters.get("status")
                )

            if filters.get("categoryCode"):
                query = query.filter(
                    IndentMaster.category_code ==
                    filters.get("categoryCode")
                )

        indents = (
            query
            .order_by(IndentMaster.id.desc())
            .all()
        )

        data = []

        for row in indents:

            data.append({

                "id": row.id,

                "indentNo": row.indent_no,

                "projectCode": row.project_code,

                "categoryCode": row.category_code,

                "indentCategoryName": row.category.category_name,

                "priority": row.priority,

                "indentStatus": row.indent_status,

                "orderStatus": row.order_status,
                "indentDate" : row.indent_date,
                "placedBy" : row.creator.username,
                "createdAt": row.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ) if row.created_at else None
            })

        return res(
            "Indent list fetched successfully",
            data,
            200
        )

    except Exception as e:

        return res(str(e), [], 500)


# =========================================================
# GET SINGLE INDENT
# =========================================================

def get_indent_details(indent_id):

    try:

        indent = IndentMaster.query.get(indent_id)

        if not indent:
            return res("Indent not found", [], 404)

        item_rows = []

        for row in indent.indent_items:

            item_rows.append({

                "id": row.id,

                "itemCode": row.item_code,

                "itemName": row.item.item_name
                if row.item else None,

                "qty": float(row.qty),

                "location": row.location,

                "note": row.note,

                "unit": (
                    row.item.unit.short_name
                    if row.item and row.item.unit
                    else None
                )
            })

        response = {

            "id": indent.id,

            "indentNo": indent.indent_no,

            "projectCode": indent.project_code,

            "categoryCode": indent.category_code,

            "priority": indent.priority,

            "requiredWithin": str(indent.required_within)
            if indent.required_within else None,

            "indentPlacedBy": indent.indent_placed_by,

            "remarks": indent.remarks,

            "indentStatus": indent.indent_status,

            "items": item_rows
        }

        return res(
            "Indent details fetched successfully",
            response,
            200
        )

    except Exception as e:

        return res(str(e), [], 500)

def get_items_by_category(category_code):

    try:

        items = Item.query.filter_by(
            category_code=category_code,
            status="Active"
        ).all()

        result = []

        for row in items:

            result.append({

                "itemCode": row.item_code,

                "itemName": row.item_name,

                "description": row.item_description,

                "unit": (
                    row.unit.short_name
                    if row.unit else None
                ),

                "gst": (
                    float(row.gst_percentage)
                    if row.gst_percentage else 0
                )
            })

        return res(
            "Items fetched successfully",
            result,
            200
        )

    except Exception as e:

        return res(str(e), [], 500)

def update_indent(indent_id, data, updated_by=None):

    try:

        indent = IndentMaster.query.get(indent_id)

        if not indent:
            return res("Indent not found", [], 404)

        # ==========================================
        # ALLOW ONLY DRAFT EDIT
        # ==========================================

        if indent.indent_status != "Draft":
            return res(
                "Only draft indent can be edited",
                [],
                400
            )

        # ==========================================
        # VALIDATE PROJECT
        # ==========================================

        project = Project.query.filter_by(
            project_code=data.get("projectCode")
        ).first()

        if not project:
            return res("Invalid project code", [], 400)

        # ==========================================
        # VALIDATE CATEGORY
        # ==========================================

        category = CategoryMaster.query.filter_by(
            fixed_code=data.get("categoryCode")
        ).first()

        if not category:
            return res("Invalid category code", [], 400)

        # ==========================================
        # VALIDATE ITEMS
        # ==========================================

        items = data.get("items", [])

        if not items:
            return res("Indent items required", [], 400)

        # ==========================================
        # UPDATE MASTER
        # ==========================================

        # indent.project_code = data.get("projectCode")

        indent.category_code = data.get("categoryCode")

        indent.priority = data.get("priority")

        indent.required_within = data.get(
            "requiredWithin"
        )

        indent.indent_placed_by = data.get(
            "indentPlacedBy"
        )

        indent.site_reg_serial_no = data.get(
            "siteRegSerialNo"
        )

        indent.sale_order_no = data.get(
            "saleOrderNo"
        )
        indent.indent_status=data.get("status")
        indent.remarks = data.get("remarks")

        indent.updated_by = updated_by

        indent.updated_at = datetime.utcnow()

        # ==========================================
        # DELETE OLD ITEMS
        # ==========================================

        IndentItem.query.filter_by(
            indent_id=indent.id
        ).delete()


        # ADD NEW ITEMS


        for row in items:

            item = Item.query.filter_by(
                item_code=row.get("itemCode")
            ).first()

            if not item:
                db.session.rollback()

                return res(
                    f"Invalid item code : "
                    f"{row.get('itemCode')}",
                    [],
                    400
                )

            # ======================================
            # CATEGORY MATCH VALIDATION
            # ======================================

            if item.category_code != data.get(
                "categoryCode"
            ):

                db.session.rollback()

                return res(
                    f"Item {item.item_code} "
                    f"does not belong to category "
                    f"{data.get('categoryCode')}",
                    [],
                    400
                )

            # ======================================
            # QTY VALIDATION
            # ======================================

            qty = row.get("qty")

            if not qty or float(qty) <= 0:

                db.session.rollback()

                return res(
                    f"Invalid qty for item "
                    f"{item.item_code}",
                    [],
                    400
                )

            indent_item = IndentItem(

                indent_id=indent.id,

                item_code=item.item_code,

                qty=qty,

                location=row.get("location"),

                note=row.get("note"),

                created_by=updated_by
            )

            db.session.add(indent_item)

        db.session.commit()

        return res(
            "Indent updated successfully",
            {
                "indentId": indent.id,
                "indentNo": indent.indent_no
            },
            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


# SUBMIT INDENT


def submit_indent(indent_id, submitted_by=None):

    try:

        indent = IndentMaster.query.get(indent_id)

        if not indent:
            return res("Indent not found", [], 404)

        # ==========================================
        # ALREADY SUBMITTED
        # ==========================================

        if indent.indent_status != "Draft":

            return res(
                "Indent already submitted",
                [],
                400
            )

        # ==========================================
        # VALIDATE ITEMS EXIST
        # ==========================================

        if not indent.indent_items:

            return res(
                "Indent has no items",
                [],
                400
            )


        # SUBMIT


        indent.indent_status = "Submitted"

        indent.updated_by = submitted_by

        indent.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Indent submitted successfully",
            {
                "indentId": indent.id,
                "indentNo": indent.indent_no,
                "status": indent.indent_status
            },
            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


# =========================================================
# DELETE DRAFT INDENT
# =========================================================

def delete_indent(indent_id):

    try:

        indent = IndentMaster.query.get(indent_id)

        if not indent:
            return res("Indent not found", [], 404)

        # ==========================================
        # ALLOW ONLY DRAFT DELETE
        # ==========================================

        if indent.indent_status != "Draft":

            return res(
                "Only draft indent can be deleted",
                [],
                400
            )

        # ==========================================
        # DELETE ITEMS
        # ==========================================

        IndentItem.query.filter_by(
            indent_id=indent.id
        ).delete()

        # ==========================================
        # DELETE MASTER
        # ==========================================

        db.session.delete(indent)

        db.session.commit()

        return res(
            "Indent deleted successfully",
            [],
            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)