from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
import time
from datetime import datetime,date
from app.models.orderMaster import OrderMaster
from app.models.orderMaster  import OrderItem
from app.models.orderMaster  import OrderTermsCondition
from app.models.indent_item import IndentItem
from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.item import Item
from app.models.cc_code import CCCode
from app.response import res
from app.cloudinary_uploader import *
from app.modules.work_flow import *
from app.models.term_conditions import *
from app.models.unit import Unit
from app.models.category_group import *
import json

from app.models.vendor import *


def get_cc_code_summary(order_id):

    rows = (

        db.session.query(

            CCCode.cc_code,

            CCCode.cc_name,

            func.sum(
                OrderItem.amount
            ).label("basic_amount"),

            func.sum(
                OrderItem.gst_amount
            ).label("gst_amount")

        )

        .join(
            Item,
            Item.item_code == OrderItem.item_code
        )

        .join(
            CCCode,
            CCCode.id == Item.cc_code_id
        )

        .filter(
            OrderItem.order_id == order_id
        )

        .group_by(
            CCCode.cc_code,
            CCCode.cc_name
        )

        .all()

    )

    return [

        {
            "ccCode": row.cc_code,
            "ccName": row.cc_name,
            "basicAmount": float(row.basic_amount or 0),
            "gstAmount": float(row.gst_amount or 0),
            "totalAmount": float(
                (row.basic_amount or 0) +
                (row.gst_amount or 0)
            )
        }

        for row in rows

    ]


def generate_order_no():

    last_order=(

        db.session.query(

            OrderMaster.order_no

        )

        .order_by(

            OrderMaster.id.desc()

        )

        .first()

    )


    if last_order:

        try:

            last_serial=int(

                last_order[0]

            )

        except:

            last_serial=440000

    else:

        last_serial=440000


    return str(

        last_serial+1

    )








def create_order(
        data,
        user_id,
files=None,
):
    start = time.time()
    allowed = is_creator(

        data.get(
            "projectCode"
        ),

        "order",

        user_id
    )

    if not allowed:
        return res(

            "You are not order creator",

            [],

            403
        )

    try:

        items = data.get(
            "items",
            []
        )

        terms = data.get(
            "terms",
            []
        )

        if isinstance(items, str):
            items = json.loads(items)

        if isinstance(terms, str):
            terms = json.loads(terms)


        if not items:

            return res(
                "No items selected",
                [],
                400
            )

        supporting_file = None

        order_file = files.get(
            "orderFile"
        )

        if not order_file:
            return res(

                "Order file required",

                [],

                400
            )

        xtemp=generate_order_no()
        print("Before upload:", time.time() - start)
        supporting_file = (

            upload_file_to_bunny(

                file=
                order_file,

                mainFolder=
                "order",

                subFolder= xtemp,

                fileName=
                "support"

            )

        )
        if not supporting_file:
            return res("ladle miaooo", [], 400)

        order=OrderMaster(

            order_no=xtemp,

            project_code=data.get(
                "projectCode"
            ),

            category_code=data.get(
                "categoryCode"
            ),
            sub_code=data.get("subCategoryCode"),

            cost_head=data.get("costHead"),
            vendor_id=data.get(
                "vendorId"
            ),

            order_date=data.get(
                "orderDate"
            ),

            validity_date=data.get(
                "validityDate"
            ),
            quotation_no=data.get("quotationNo"),
            quotation_date=data.get("quotationDate"),

            billing_address=data.get(
                "billingAddress"
            ),

            shipping_address=data.get(
                "shippingAddress"
            ),

            order_message=data.get(
                "orderMessage"
            ),
            supporting_file=
            supporting_file,

            workflow_status=
            "Draft",

            current_level=
            0,

            locked=
            False,

            created_by=user_id


        )

        db.session.add(
            order
        )

        db.session.flush()


        total_basic=0
        total_gst=0


        for row in items:

            indent_item_id=row.get(
                "indentItemId"
            )

            requested_qty=float(
                row.get(
                    "qty",
                    0
                )
            )


            indent_item=IndentItem.query.get(
                indent_item_id
            )


            if not indent_item:

                db.session.rollback()

                return res(
                    f"Indent item {indent_item_id} not found",
                    [],
                    404
                )


            previous_qty=(

                db.session.query(

                    func.coalesce(
                        func.sum(
                            OrderItem.qty
                        ),
                        0
                    )

                )

                .filter(
                    OrderItem.indent_item_id==
                    indent_item_id
                )

                .scalar()

            )


            remaining_qty=float(
                indent_item.qty
            )-float(
                previous_qty
            )


            if requested_qty<=0:

                db.session.rollback()

                return res(
                    f"Invalid qty for item {indent_item.item_code}",
                    [],
                    400
                )


            if requested_qty>remaining_qty:

                db.session.rollback()

                return res(
                    f"Available qty only {remaining_qty} for item {indent_item.item_code}",
                    [],
                    400
                )


            rate=float(
                row.get(
                    "rate",
                    0
                )
            )

            gst_percent=float(
                row.get(
                    "gstPercent",
                    0
                )
            )

            amount=(
                requested_qty*
                rate
            )

            gst_amount=(
                amount*
                gst_percent
            )/100


            order_item=OrderItem(

                order_id=order.id,

                indent_item_id=
                indent_item_id,

                item_code=
                indent_item.item_code,

                custom_note= row.get("note") or indent_item.note,

                qty=
                requested_qty,

                balance_qty=
                remaining_qty-requested_qty,
                location=
                indent_item.location,

                rate=rate,

                amount=amount,

                gst_percent=
                gst_percent,

                gst_amount=
                gst_amount
            )

            db.session.add(
                order_item
            )


            total_basic+=amount
            total_gst+=gst_amount

        for idx, row in enumerate(terms, start=1):

            term = TermConditions.query.get(
                row.get("termId")
            )

            if not term:
                db.session.rollback()

                return res(
                    f"Term {row.get('termId')} not found",
                    [],
                    404
                )

            db.session.add(

                OrderTermsCondition(

                    order_id=order.id,

                    term_id=term.id,

                    custom_description=
                    row.get(
                        "description"
                    ) or None,

                    sequence_no=
                    row.get(
                        "sequenceNo",
                        idx
                    ),

                    created_by=user_id
                )
            )


        order.basic_amount=total_basic

        order.gst_amount=total_gst

        order.total_amount=(
            total_basic+
            total_gst
        )


        db.session.commit()


        cc_summary = get_cc_code_summary(
            order.id
        )

        return res(
            "Order created",
            {
                "orderId":
                order.id,

                "orderNo":
                order.order_no,

                "ccSummary":
                cc_summary
            },
            201
        )


    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )

def get_indent_pending_qty_list(
        project_code,
        sub_code,
        asset_only=False):

    try:

        result=[]

        query = (

            db.session.query(

                IndentMaster.indent_no,

                IndentItem.id.label(
                    "indent_item_id"
                ),

                IndentItem.item_code,

                Item.item_name,

                Unit.unit_name.label(
                    "item_unit"
                ),

                IndentItem.qty.label(
                    "indent_qty"
                ),
                IndentItem.note,
                IndentItem.location,

                func.coalesce(

                    func.sum(
                        OrderItem.qty
                    ),

                    0

                ).label(
                    "used_qty"
                )

            )

            .join(
                IndentItem,
                IndentMaster.id ==
                IndentItem.indent_id
            )

            .join(
                Item,
                Item.item_code ==
                IndentItem.item_code
            )
            .join(
                CCCode,
                CCCode.id == Item.cc_code_id
            )

            .join(
                GroupMaster,
                GroupMaster.id == CCCode.group_id
            )
            .outerjoin(
                Unit,
                Unit.id ==
                Item.unit_id
            )

            .outerjoin(
                OrderItem,

                OrderItem.indent_item_id ==
                IndentItem.id
            )

            .filter(

                IndentMaster.project_code ==
                project_code,

                IndentMaster.category_code ==
                sub_code,

                IndentMaster.workflow_status ==
                "Approved"

            )
        )

        if asset_only:

            query = query.filter(
            GroupMaster.group_name == "FIXED ASSET"
        )

        else:

            query = query.filter(
            GroupMaster.group_name != "FIXED ASSET"
        )

        rows=(query .group_by(

                IndentMaster.indent_no,

                IndentItem.id,

                IndentItem.item_code,

                Item.item_name,

                Unit.unit_name,

                IndentItem.qty,

                IndentItem.location
            )

            .all()


        )

        for row in rows:

            used_qty = float(
                row.used_qty
            )

            balance_qty = (

                    float(
                        row.indent_qty
                    )

                    -

                    used_qty
            )

            if balance_qty <= 0:
                continue


            result.append({

                "indentItemId":
                row.indent_item_id,

                "indentNo":
                row.indent_no,

                "itemCode":
                row.item_code,

                "note":
                row.note,

                "itemName":
                row.item_name,
                "itemUnit":
                row.item_unit,
                "indentQty":
                float(
                    row.indent_qty
                ),

                "usedQty":
                float(
                    used_qty
                ),

                "balanceQty":
                balance_qty,

                "orderQty":
                balance_qty,

                "location":
                row.location

            })


        return res(
            "Indent list fetched",
            result,
            200
        )


    except Exception as e:

        return res(
            str(e),
            [],
            500
        )

def get_order_details(
        order_id
):

    try:

        order=(
            OrderMaster.query
            .filter_by(
                id=order_id
            )
            .first()
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )


        items=[]

        for item in order.items:

            items.append({

                "id":
                item.id,

                "indentItemId":
                item.indent_item_id,

                "indentNo":
                item.indent_item.indent.indent_no,

                "itemCode":
                item.item_code,

                "itemUnit":
                item.item.unit.unit_name ,

                "itemName":
                item.item.item_name
                if item.item
                else None,

                "note":item.custom_note ,


                "qty":
                float(item.qty),

                "amendQty":
                float(
                    item.amend_qty or 0
                ),

                "rate":
                float(
                    item.rate or 0
                ),

                "amount":
                float(
                    item.amount or 0
                ),

                "gstPercent":
                float(
                    item.gst_percent or 0
                ),

                "gstAmount":
                float(
                    item.gst_amount or 0
                ),

                "location":
                item.location,

                "balanceQty":
                float(
                    item.balance_qty or 0
                )
            })


        terms=[]

        for t in order.terms_conditions:

            terms.append({

                "id":
                t.id,

                "termId":
                t.term_id,

                "header":
                t.term.header,

                "subHeader":
                t.term.sub_header,

                "description":
                (
                    t.custom_description
                    or
                    t.term.term_description
                )

            })
        cc_summary = get_cc_code_summary(
            order.id
        )

        data={

            "id":
            order.id,

            "orderNo":
            order.order_no,

            "projectCode":
            order.project_code,

            "projectName":
            order.project.project_name,

            "orderFile": order.supporting_file ,
            "subCategoryCode":order.sub_code,
            "categoryCode": order.category_code,
            "costHead": order.cost_head,
            "vendorId":order.vendor_id,

            "orderDate":
            str( order.order_date ),

            "validityDate":
            str( order.validity_date )
            if order.validity_date
            else None,

            "billingAddress":
            order.billing_address,

            "shippingAddress":
            order.shipping_address,

            "orderMessage":
            order.order_message,
            "bookedAmount":order.booked_amount,
            "quotationNo":order. quotation_no,
            "quotationDate":order.quotation_date.strftime(
                    "%Y-%m-%d"),
            "basicAmount":
            float(
                order.basic_amount
            ),

            "gstAmount":
            float(
                order.gst_amount
            ),

            "totalAmount":
            float(
                order.total_amount
            ),

            "workflowStatus":
            order.workflow_status,

            "items":
            items,

            "ccSummary":cc_summary,

            "terms":
            terms
        }

        return res(
            "Order details fetched",
            data,
            200
        )

    except Exception as e:

        return res(
            str(e),
            [],
            500
        )

def get_order_list(
        data
):

    try:

        # REQUIRED
        if not data.get(
                "projectCode"
        ):

            return res(

                "projectCode required",

                [],

                400
            )


        query=OrderMaster.query.filter(

            OrderMaster.project_code==

            data.get(
                "projectCode"
            )

        )


        # OPTIONAL
        if data.get(
                "subCategoryCode"
        ):

            query=query.filter(

                OrderMaster.sub_code==

                data.get(
                    "subCategoryCode"
                )
            )


        # OPTIONAL
        if data.get(
                "categoryCode"
        ):

            query=query.filter(

                OrderMaster.category_code==

                data.get(
                    "categoryCode"
                )
            )


        if data.get(
                "workflowStatus"
        ):

            query=query.filter(

                OrderMaster.workflow_status==

                data.get(
                    "workflowStatus"
                )
            )


        if data.get(
                "search"
        ):

            query=query.filter(

                OrderMaster.order_no.ilike(

                    f"%{data.get('search')}%"
                )

            )


        rows=(
            query
            .order_by(
                OrderMaster.id.desc()
            )
            .all()
        )


        data=[]


        for row in rows:

            data.append({

                "id":
                row.id,

                "orderNo":
                row.order_no,

                "partyName":row.vendor.ledger_name,

                "projectCode":
                row.project_code,

                "projectName":
                row.project.project_name
                if row.project
                else None,

                "orderDate":
                str(
                    row.order_date
                ),

                "categoryCode":
                row.category_code,

                "basicAmount":
                float(
                    row.basic_amount
                    or 0
                ),

                "gstAmount":
                float(
                    row.gst_amount
                    or 0
                ),

                "totalAmount":
                float(
                    row.total_amount
                    or 0
                ),

                "status":
                row.workflow_status,
                "booked":row.booked_amount

            })


        return res(
            "Orders fetched",
            data,
            200
        )


    except Exception as e:

        return res(
            str(e),
            [],
            500
        )

def submit_order(
        order_id,
        submitted_by=None
):

    try:

        order = OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )

        # ==========================================
        # ONLY DRAFT / REBACK CAN SUBMIT
        # ==========================================

        if order.workflow_status not in [
            "Draft",
            "Reback"
        ]:

            return res(
                "Order already submitted",
                [],
                400
            )

        # ==========================================
        # MUST HAVE ITEMS
        # ==========================================

        if not order.items:

            return res(
                "Order has no items",
                [],
                400
            )

        # ==========================================
        # RESTART LEVEL ON REBACK
        # ==========================================

        if order.workflow_status == "Reback":

            order.current_level = 0

        # ==========================================
        # FIND FIRST APPROVER
        # ==========================================

        first_level = get_first_approver(

            order.project_code,

            "order"
        )

        # ==========================================
        # NO APPROVER → AUTO APPROVE
        # ==========================================

        if not first_level:

            order.workflow_status = "Approved"

            order.locked = True

            order.approved_by = submitted_by

            order.submitted_at = datetime.utcnow()

            order.final_approved_at = datetime.utcnow()

        else:

            order.workflow_status = (
                f"Pending_L{first_level.level_no}"
            )

            order.current_level = (
                first_level.level_no
            )

            order.locked = True

            order.submitted_at = datetime.utcnow()

        # ==========================================
        # HISTORY
        # ==========================================

        create_history(

            project_code=order.project_code,

            module_code="order",

            record_id=order.id,

            level_no=order.current_level,

            action="SUBMIT",

            action_by=submitted_by
        )

        order.updated_by = submitted_by
        order.submitted_by = submitted_by
        order.updated_at = datetime.utcnow()

        db.session.commit()

        return res(

            "Order submitted successfully",

            {
                "orderId": order.id,
                "orderNo": order.order_no,
                "workflowStatus": order.workflow_status
            },

            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


def approve_order(
        order_id,
        approved_by=None,
        comments=None
):

    try:

        order = OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )

        # ==========================================
        # ONLY PENDING CAN APPROVE
        # ==========================================

        if not order.workflow_status.startswith(
            "Pending"
        ):

            return res(
                "Order not pending",
                [],
                400
            )

        # ==========================================
        # CHECK CURRENT APPROVER
        # ==========================================

        allowed = is_current_approver(

            order.project_code,

            "order",

            order.current_level,

            approved_by
        )

        if not allowed:

            return res(
                "You are not current approver",
                [],
                403
            )

        # ==========================================
        # FIND NEXT LEVEL
        # ==========================================

        next_level = get_next_approver(

            order.project_code,

            "order",

            order.current_level
        )

        if next_level:

            # ======================================
            # INTERMEDIATE → ADVANCE LEVEL
            # ======================================

            create_history(

                project_code=order.project_code,

                module_code="order",

                record_id=order.id,

                level_no=order.current_level,

                action="APPROVE",

                action_by=approved_by,

                comments=comments
            )

            order.current_level = next_level.level_no

            order.workflow_status = (
                f"Pending_L{next_level.level_no}"
            )

        else:

            # ======================================
            # FINAL APPROVAL
            # ======================================

            create_history(

                project_code=order.project_code,

                module_code="order",

                record_id=order.id,

                level_no=order.current_level,

                action="FINAL_APPROVE",

                action_by=approved_by,

                comments=comments
            )

            order.workflow_status = "Approved"

            order.locked = True

            order.approved_by = approved_by

            order.final_approved_at = datetime.utcnow()

        order.updated_by = approved_by

        order.updated_at = datetime.utcnow()

        db.session.commit()

        return res(

            "Order approved successfully",

            {
                "orderId": order.id,
                "workflowStatus": order.workflow_status,
                "currentLevel": order.current_level
            },

            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


def reback_order(
        order_id,
        reback_by=None,
        comments=None
):

    try:

        order = OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )

        # ==========================================
        # ONLY PENDING CAN REBACK
        # ==========================================

        if not order.workflow_status.startswith(
            "Pending"
        ):

            return res(
                "Order not pending",
                [],
                400
            )

        # ==========================================
        # COMMENT REQUIRED
        # ==========================================

        if not comments:

            return res(
                "Comments required",
                [],
                400
            )

        # ==========================================
        # CURRENT APPROVER CHECK
        # ==========================================

        allowed = is_current_approver(

            order.project_code,

            "order",

            order.current_level,

            reback_by
        )

        if not allowed:

            return res(
                "You are not current approver",
                [],
                403
            )

        order.workflow_status = "Reback"

        order.locked = False

        order.correction_sent_at = datetime.utcnow()

        order.updated_by = reback_by

        order.updated_at = datetime.utcnow()

        create_history(

            project_code=order.project_code,

            module_code="order",

            record_id=order.id,

            level_no=order.current_level,

            action="REBACK",

            action_by=reback_by,

            comments=comments
        )

        db.session.commit()

        return res(

            "Order sent for correction",

            {
                "orderId": order.id,
                "workflowStatus": order.workflow_status
            },

            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)


def reject_order(
        order_id,
        rejected_by=None,
        comments=None
):

    try:

        order = OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )

        # ==========================================
        # ONLY PENDING CAN REJECT
        # ==========================================

        if not order.workflow_status.startswith(
            "Pending"
        ):

            return res(
                "Order not pending",
                [],
                400
            )

        # ==========================================
        # COMMENT REQUIRED
        # ==========================================

        if not comments:

            return res(
                "Comments required",
                [],
                400
            )

        # ==========================================
        # CURRENT APPROVER CHECK
        # ==========================================

        allowed = is_current_approver(

            order.project_code,

            "order",

            order.current_level,

            rejected_by
        )

        if not allowed:

            return res(
                "You are not current approver",
                [],
                403
            )

        order.workflow_status = "Rejected"

        order.locked = True

        order.rejected_at = datetime.utcnow()

        order.rejected_by = rejected_by

        order.status = "Inactive"

        order.updated_by = rejected_by

        order.updated_at = datetime.utcnow()

        create_history(

            project_code=order.project_code,

            module_code="order",

            record_id=order.id,

            level_no=order.current_level,

            action="REJECT",

            action_by=rejected_by,

            comments=comments
        )

        db.session.commit()

        return res(

            "Order rejected successfully",

            {
                "orderId": order.id,
                "workflowStatus": order.workflow_status
            },

            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(str(e), [], 500)

    except Exception as e:

        db.session.rollback()

        return res(str(e), [], 500)

def delete_order(
        order_id
):

    try:

        order=OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )


        # =============================
        # ALLOW ONLY EDITABLE
        # =============================

        if order.locked:

            return res(

                "Only Draft/Reback order can delete",

                [],

                400
            )


        # =============================
        # DELETE ITEMS
        # =============================

        OrderItem.query.filter_by(

            order_id=order.id

        ).delete()


        # =============================
        # DELETE TERMS
        # =============================

        if hasattr(
                order,
                "terms_conditions"
        ):

            for row in order.terms_conditions:

                db.session.delete(
                    row
                )


        # =============================
        # DELETE MASTER
        # =============================

        db.session.delete(
            order
        )

        db.session.commit()


        return res(

            "Order deleted successfully",

            [],

            200
        )

    except SQLAlchemyError as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )

    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )


def get_order_history(
        order_id
):

    try:

        order=OrderMaster.query.get(
            order_id
        )

        if not order:

            return res(
                "Order not found",
                [],
                404
            )

        rows=get_history(

            "order",

            order.id
        )

        data=[]

        for row in rows:

            data.append({

                "id":
                row.id,

                "action":
                row.action,

                "level":
                row.level_no,

                "comments":
                row.comments,

                "actionBy":
                (
                    row.user.username
                    if row.user
                    else None
                ),

                "createdAt":
                row.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if row.created_at
                else None
            })

        return res(

            "Order history fetched",

            data,

            200
        )

    except Exception as e:

        return res(
            str(e),
            [],
            500
        )



def edit_order(order_id, data, user_id, files=None):
    try:

        order = OrderMaster.query.get(order_id)

        if not order:
            return res("Order not found", [], 404)

        # ── lock check ────────────────────────────────────────
        if order.locked:
            return res("Order cannot be edited", [], 400)

        # ── creator check (was missing) ───────────────────────
        allowed = is_creator(order.project_code, "order", user_id)
        if not allowed:
            return res("You are not order creator", [], 403)

        # ── basic validation ──────────────────────────────────
        items = data.get("items")
        if not items:
            return res("Items required", [], 400)


        # ── header fields ─────────────────────────────────────
        order.vendor_id = data.get("vendorId", order.vendor_id)
        order.order_date = data.get("orderDate", order.order_date)
        order.validity_date = data.get("validityDate", order.validity_date)
        order.billing_address = data.get("billingAddress", order.billing_address)
        order.shipping_address = data.get("shippingAddress", order.shipping_address)
        order.order_message = data.get("orderMessage",order.order_message)
        order.quotation_no = data.get("quotationNo", order.quotation_no)
        order.quotation_date=data.get("quotationDate",order.quotation_date)


        # ── file update ───────────────────────────────────────
        if files:
            order_file = files.get("orderFile")
            if order_file:
                order.supporting_file = upload_file_to_bunny(
                    file=order_file,
                    mainFolder="order",
                    subFolder=order.id,
                    fileName="support"
                )

        # ── wipe old items & terms ────────────────────────────
        # Delete first so previous_qty query below excludes this order cleanly
        OrderItem.query.filter_by(order_id=order.id).delete()
        OrderTermsCondition.query.filter_by(order_id=order.id).delete()
        db.session.flush()  # flush so subquery sees deletions

        # ── rebuild items ─────────────────────────────────────
        total_basic = 0
        total_gst = 0

        if isinstance(items, str):
            items = json.loads(items)



        for row in items:

            indent_item_id = row.get("indentItemId")
            qty = float(row.get("qty", 0))

            indent_item = IndentItem.query.get(indent_item_id)
            if not indent_item:
                db.session.rollback()
                return res("Indent item not found", [], 404)

            # qty already used by OTHER orders (current order wiped above)
            previous_qty = (
                db.session.query(
                    func.coalesce(func.sum(OrderItem.qty), 0)
                )
                .filter(OrderItem.indent_item_id == indent_item_id)
                .scalar()
            )

            remaining_qty = float(indent_item.qty) - float(previous_qty)

            if qty <= 0:
                db.session.rollback()
                return res(f"Invalid qty for {indent_item.item_code}", [], 400)

            if qty > remaining_qty:
                db.session.rollback()
                return res(
                    f"Only {remaining_qty} available for {indent_item.item_code}",
                    [], 400
                )

            rate = float(row.get("rate", 0))
            gst = float(row.get("gstPercent", 0))
            amount = qty * rate
            gst_amount = (amount * gst) / 100

            db.session.add(OrderItem(
                order_id=order.id,
                indent_item_id=indent_item.id,
                item_code=indent_item.item_code,
                custom_note=row.get("note") or indent_item.note,
                qty=qty,
                balance_qty=remaining_qty - qty,
                location=indent_item.location,
                rate=rate,
                amount=amount,
                gst_percent=gst,
                gst_amount=gst_amount,
            ))

            total_basic += amount
            total_gst += gst_amount

        # ── rebuild terms ─────────────────────────────────────
        terms = data.get("terms", [])

        if isinstance(terms, str):
            terms = json.loads(terms)

        for idx, row in enumerate(terms, start=1):

            term = TermConditions.query.get(row.get("termId"))
            if not term:
                db.session.rollback()
                return res(f"Term {row.get('termId')} not found", [], 404)

            db.session.add(OrderTermsCondition(
                order_id=order.id,
                term_id=term.id,
                # caller can pass customised text; falls back to master in get_order_details
                custom_description=row.get("description") or None,
                sequence_no=row.get("sequenceNo", idx),
                created_by=user_id,
            ))

        # ── totals ────────────────────────────────────────────
        order.basic_amount = total_basic
        order.gst_amount = total_gst
        order.total_amount = total_basic + total_gst

        # clear reback timestamp when creator resubmits edits
        if order.workflow_status == "Reback":
            order.correction_sent_at = None

        order.updated_by = user_id
        order.updated_at = datetime.utcnow()

        db.session.commit()

        data=[{"orderId": order.id, "orderNo": order.order_no}]
        return res(
            "Order updated successfully",
            data,
            200,
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)