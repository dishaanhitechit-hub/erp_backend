from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.response import res
from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.item import Item

from app.models.enquiry_master import EnquiryMaster
from app.models.enquiry_item import EnquiryItem
from app.models.enquiry_term import EnquiryTerm
from app.cloudinary_uploader import *

# =========================================================
# GENERATE ENQUIRY NUMBER
# =========================================================

def generate_enquiry_no(project_code):

    today = datetime.now().strftime("%Y%m")

    last_enquiry = (
        EnquiryMaster.query
        .filter(
            EnquiryMaster.project_code == project_code
        )
        .order_by(EnquiryMaster.id.desc())
        .first()
    )

    if last_enquiry:
        try:
            last_serial = int(
                last_enquiry.enquiry_no.split("-")[-1]
            )
        except Exception:
            last_serial = 0
    else:
        last_serial = 0

    new_serial = str(last_serial + 1).zfill(4)

    return f"ENQ-{project_code}-{today}-{new_serial}"


# =========================================================
# GET INDENT ITEMS FOR ENQUIRY FORM
# =========================================================

def get_indent_items_for_enquiry(indent_id):
    """
    Returns indent master + its items so the
    frontend can pre-fill the enquiry form.
    """
    try:

        indent = IndentMaster.query.get(indent_id)

        if not indent:
            return res("Indent not found", [], 404)

        if indent.indent_status != "Submitted":
            return res(
                "Only submitted indents can be used "
                "for enquiry",
                [],
                400
            )

        items = []

        for row in indent.indent_items:

            items.append({
                "indentItemId": row.id,
                "itemCode":     row.item_code,
                "itemName": (
                    row.item.item_name
                    if row.item else None
                ),
                "unit": (
                    row.item.unit.short_name
                    if row.item and row.item.unit
                    else None
                ),
                "indentQty":  float(row.qty),
                "note":       row.location,
                "location":   row.location,
            })

        data = {
            "indentId":     indent.id,
            "indentNo":     indent.indent_no,
            "projectCode":  indent.project_code,
            "categoryCode": indent.category_code,
            "items":        items,
        }

        return res(
            "Indent items fetched successfully",
            data,
            200
        )

    except Exception as e:
        return res(str(e), [], 500)


# =========================================================
# CREATE ENQUIRY
# =========================================================

def create_enquiry(data, created_by=None):

    try:

        # --------------------------------------------------
        # VALIDATE INDENT
        # --------------------------------------------------

        indent = IndentMaster.query.get(
            data.get("indentId")
        )

        if not indent:
            return res("Invalid indent id", [], 400)

        if indent.indent_status != "Submitted":
            return res(
                "Only submitted indents can be used "
                "for enquiry",
                [],
                400
            )

        # --------------------------------------------------
        # VALIDATE ITEMS
        # --------------------------------------------------

        items = data.get("items", [])

        if not items:
            return res("Enquiry items required", [], 400)

        # --------------------------------------------------
        # CREATE MASTER
        # --------------------------------------------------

        enquiry = EnquiryMaster(

            enquiry_no=generate_enquiry_no(
                indent.project_code
            ),

            enquiry_date=datetime.utcnow(),

            indent_id=indent.id,

            project_code=indent.project_code,

            category_code=indent.category_code,

            enquiry_to=data.get("enquiryTo"),

            address=data.get("address"),

            enquiry_status="Draft",

            created_by=created_by
        )

        db.session.add(enquiry)
        db.session.flush()

        # --------------------------------------------------
        # CREATE ITEMS
        # --------------------------------------------------

        for row in items:

            indent_item = IndentItem.query.get(
                row.get("indentItemId")
            )

            if not indent_item:
                db.session.rollback()
                return res(
                    f"Invalid indent item id: "
                    f"{row.get('indentItemId')}",
                    [],
                    400
                )

            enquiry_qty = row.get("enquiryQty")

            if not enquiry_qty or float(enquiry_qty) <= 0:
                db.session.rollback()
                return res(
                    f"Invalid enquiry qty for item "
                    f"{indent_item.item_code}",
                    [],
                    400
                )

            # enquiry qty must not exceed indent qty
            if float(enquiry_qty) > float(indent_item.qty):
                db.session.rollback()
                return res(
                    f"Enquiry qty cannot exceed indent "
                    f"qty for item "
                    f"{indent_item.item_code}",
                    [],
                    400
                )

            enq_item = EnquiryItem(

                enquiry_id=enquiry.id,

                indent_item_id=indent_item.id,

                item_code=indent_item.item_code,

                indent_qty=float(indent_item.qty),

                enquiry_qty=float(enquiry_qty),

                location=row.get("location"),

                note=row.get("note"),

                created_by=created_by
            )

            db.session.add(enq_item)

        # --------------------------------------------------
        # TERMS & CONDITIONS
        # --------------------------------------------------

        terms = data.get("terms", [])

        for term in terms:

            t = EnquiryTerm(

                enquiry_id=enquiry.id,

                header=term.get("header"),

                description=term.get("description"),

                created_by=created_by
            )

            db.session.add(t)

        # --------------------------------------------------
        # COMMIT
        # --------------------------------------------------

        db.session.commit()

        return res(
            "Enquiry created successfully",
            {
                "enquiryId": enquiry.id,
                "enquiryNo": enquiry.enquiry_no
            },
            201
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# =========================================================
# ENQUIRY LIST
# =========================================================

def get_enquiry_list(filters=None):

    try:

        query = EnquiryMaster.query

        if filters:

            if filters.get("projectCode"):
                query = query.filter(
                    EnquiryMaster.project_code ==
                    filters["projectCode"]
                )

            if filters.get("status"):
                query = query.filter(
                    EnquiryMaster.enquiry_status ==
                    filters["status"]
                )

            if filters.get("categoryCode"):
                query = query.filter(
                    EnquiryMaster.category_code ==
                    filters["categoryCode"]
                )

        enquiries = (
            query
            .order_by(EnquiryMaster.id.desc())
            .all()
        )

        data = []

        for row in enquiries:

            data.append({
                "id":           row.id,
                "enquiryNo":    row.enquiry_no,
                "enquiryDate":  row.enquiry_date.strftime(
                    "%Y-%m-%d"
                ) if row.enquiry_date else None,
                "projectCode":  row.project_code,
                "categoryCode": row.category_code,
                "enquiryTo":    row.enquiry_to,
                "enquiryStatus": row.enquiry_status,
                "createdAt":    row.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ) if row.created_at else None,
            })

        return res(
            "Enquiry list fetched successfully",
            data,
            200
        )

    except Exception as e:
        return res(str(e), [], 500)


# =========================================================
# GET SINGLE ENQUIRY
# =========================================================

def get_enquiry_details(enquiry_id):

    try:

        enquiry = EnquiryMaster.query.get(enquiry_id)

        if not enquiry:
            return res("Enquiry not found", [], 404)

        item_rows = []

        for row in enquiry.enquiry_items:

            item_rows.append({
                "id":           row.id,
                "indentItemId": row.indent_item_id,
                "itemCode":     row.item_code,
                "itemName": (
                    row.item.item_name
                    if row.item else None
                ),
                "unit": (
                    row.item.unit.short_name
                    if row.item and row.item.unit
                    else None
                ),
                "indentQty":   float(row.indent_qty),
                "enquiryQty":  float(row.enquiry_qty),
                "location":    row.location,
                "note":        row.note,
            })

        term_rows = []

        for t in enquiry.enquiry_terms:

            term_rows.append({
                "id":          t.id,
                "header":      t.header,
                "description": t.description,
            })

        response = {
            "id":             enquiry.id,
            "enquiryNo":      enquiry.enquiry_no,
            "enquiryDate":    enquiry.enquiry_date.strftime(
                "%Y-%m-%d"
            ) if enquiry.enquiry_date else None,
            "indentId":       enquiry.indent_id,
            "projectCode":    enquiry.project_code,
            "categoryCode":   enquiry.category_code,
            "enquiryTo":      enquiry.enquiry_to,
            "address":        enquiry.address,
            "enquiryStatus":  enquiry.enquiry_status,
            "items":          item_rows,
            "terms":          term_rows,
        }

        return res(
            "Enquiry details fetched successfully",
            response,
            200
        )

    except Exception as e:
        return res(str(e), [], 500)


# =========================================================
# UPDATE ENQUIRY  (only Draft)
# =========================================================

def update_enquiry(enquiry_id, data, updated_by=None):

    try:

        enquiry = EnquiryMaster.query.get(enquiry_id)

        if not enquiry:
            return res("Enquiry not found", [], 404)

        if enquiry.enquiry_status != "Draft":
            return res(
                "Only draft enquiry can be edited",
                [],
                400
            )

        items = data.get("items", [])

        if not items:
            return res("Enquiry items required", [], 400)

        # --------------------------------------------------
        # UPDATE MASTER FIELDS
        # --------------------------------------------------

        enquiry.enquiry_to  = data.get("enquiryTo")
        enquiry.address     = data.get("address")
        enquiry.updated_by  = updated_by
        enquiry.updated_at  = datetime.utcnow()

        # --------------------------------------------------
        # REPLACE ITEMS
        # --------------------------------------------------

        EnquiryItem.query.filter_by(
            enquiry_id=enquiry.id
        ).delete()

        for row in items:

            indent_item = IndentItem.query.get(
                row.get("indentItemId")
            )

            if not indent_item:
                db.session.rollback()
                return res(
                    f"Invalid indent item id: "
                    f"{row.get('indentItemId')}",
                    [],
                    400
                )

            enquiry_qty = row.get("enquiryQty")

            if not enquiry_qty or float(enquiry_qty) <= 0:
                db.session.rollback()
                return res(
                    f"Invalid enquiry qty for item "
                    f"{indent_item.item_code}",
                    [],
                    400
                )

            if float(enquiry_qty) > float(indent_item.qty):
                db.session.rollback()
                return res(
                    f"Enquiry qty exceeds indent qty "
                    f"for item {indent_item.item_code}",
                    [],
                    400
                )

            enq_item = EnquiryItem(
                enquiry_id=enquiry.id,
                indent_item_id=indent_item.id,
                item_code=indent_item.item_code,
                indent_qty=float(indent_item.qty),
                enquiry_qty=float(enquiry_qty),
                location=row.get("location"),
                note=row.get("note"),
                created_by=updated_by
            )

            db.session.add(enq_item)

        # --------------------------------------------------
        # REPLACE TERMS
        # --------------------------------------------------

        EnquiryTerm.query.filter_by(
            enquiry_id=enquiry.id
        ).delete()

        for term in data.get("terms", []):

            t = EnquiryTerm(
                enquiry_id=enquiry.id,
                header=term.get("header"),
                description=term.get("description"),
                created_by=updated_by
            )

            db.session.add(t)

        db.session.commit()

        return res(
            "Enquiry updated successfully",
            {
                "enquiryId": enquiry.id,
                "enquiryNo": enquiry.enquiry_no
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
# SUBMIT ENQUIRY
# =========================================================

def submit_enquiry(enquiry_id, submitted_by=None):

    try:

        enquiry = EnquiryMaster.query.get(enquiry_id)

        if not enquiry:
            return res("Enquiry not found", [], 404)

        if enquiry.enquiry_status != "Draft":
            return res(
                "Enquiry already submitted",
                [],
                400
            )

        if not enquiry.enquiry_items:
            return res("Enquiry has no items", [], 400)

        enquiry.enquiry_status = "Submitted"
        enquiry.updated_by     = submitted_by
        enquiry.updated_at     = datetime.utcnow()

        db.session.commit()

        return res(
            "Enquiry submitted successfully",
            {
                "enquiryId":     enquiry.id,
                "enquiryNo":     enquiry.enquiry_no,
                "enquiryStatus": enquiry.enquiry_status,
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
# DELETE DRAFT ENQUIRY
# =========================================================

def delete_enquiry(enquiry_id):

    try:

        enquiry = EnquiryMaster.query.get(enquiry_id)

        if not enquiry:
            return res("Enquiry not found", [], 404)

        if enquiry.enquiry_status != "Draft":
            return res(
                "Only draft enquiry can be deleted",
                [],
                400
            )

        EnquiryItem.query.filter_by(
            enquiry_id=enquiry.id
        ).delete()

        EnquiryTerm.query.filter_by(
            enquiry_id=enquiry.id
        ).delete()

        db.session.delete(enquiry)
        db.session.commit()

        return res(
            "Enquiry deleted successfully",
            [],
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# =========================================================
# ATTACH QUOTATION  (store file path / URL)
# =========================================================

def attach_quotation(enquiryId, request):

    try:
        files = request.files

        enquiry = EnquiryMaster.query.get( enquiryId )

        if not enquiry:

            return res(
            "Enquiry not found",
            [],
            404
            )

        quotationFile = files.get(
        "quotationFile"
        )

        if quotationFile:

            quotationUrl = (upload_file_to_cloudinary(

                    file=quotationFile,

                 mainFolder="enquiry",

                subFolder=enquiry.enquiry_no,

                fileName="quotation"
            )
        )

            enquiry.quotation_url = (
            quotationUrl
            )

        db.session.commit()

        return res(

        "Quotation uploaded successfully",

        [{

            "enquiryId": enquiry.id,

            "enquiryNo": enquiry.enquiry_no,

            "quotationUrl":
                enquiry.quotation_url
         }],

        200
    )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)