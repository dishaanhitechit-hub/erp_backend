from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db

from datetime import datetime,date
from app.models.orderMaster import OrderMaster
from app.models.orderMaster  import OrderItem
from app.models.orderMaster  import OrderTermsCondition
from app.models.indent_item import IndentItem
from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.item import Item
from app.models.cc_code import CCCode
from app.workflow_engine import (

    submit_record,

    reback_record,

    reject_record

)
from app.response import res
from app.cloudinary_uploader import *
from app.modules.work_flow import *







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

        items=data.get(
            "items",
            []
        )

        terms=data.get(
            "terms",
            []
        )

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

        supporting_file = (

            upload_file_to_bunny(

                file=
                order_file,

                mainFolder=
                "order",

                subFolder=
                data.get(
                    "projectCode"
                ),

                fileName=
                "support"

            )

        )

        order=OrderMaster(

            order_no=generate_order_no(),

            project_code=data.get(
                "projectCode"
            ),

            category_code=data.get(
                "categoryCode"
            ),
            sub_code=data.get("subCategoryCode"),
            vendor_id=data.get(
                "vendorId"
            ),

            order_date=data.get(
                "orderDate"
            ),

            validity_date=data.get(
                "validityDate"
            ),

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

                note=
                indent_item.note,

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


        for term_id in terms:

            db.session.add(

                OrderTermsCondition(

                    order_id=order.id,

                    term_id=term_id,

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

                "ccCodes":
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
        sub_code ):

    try:

        result=[]


        rows=(

            db.session.query(

                IndentMaster.indent_no,

                IndentItem.id.label(
                    "indent_item_id"
                ),

                IndentItem.item_code,

                Item.item_name,

                IndentItem.qty.label(
                    "indent_qty"
                ),

                IndentItem.location

            )

            .join(

                IndentItem,

                IndentMaster.id==
                IndentItem.indent_id
            )

            .join(

                Item,

                Item.item_code==
                IndentItem.item_code
            )

            .filter(

                IndentMaster.project_code==
                project_code,

                IndentMaster.category_code==
                sub_code,

                IndentMaster.workflow_status==
                "Approved"

            )

            .all()

        )


        for row in rows:

            used_qty=(

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
                    row.indent_item_id

                )

                .scalar()

            )


            balance_qty=(
                float(
                    row.indent_qty
                )
                -
                float(
                    used_qty
                )
            )


            if balance_qty<=0:

                continue


            result.append({

                "indentItemId":
                row.indent_item_id,

                "indentNo":
                row.indent_no,

                "itemCode":
                row.item_code,

                "itemName":
                row.item_name,

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

                "itemName":
                item.item.item_name
                if item.item
                else None,

                "note":
                item.note,

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


        data={

            "id":
            order.id,

            "orderNo":
            order.order_no,

            "projectCode":
            order.project_code,

            "projectName":
            order.project.project_name,

            "attachedQuota": order.supporting_file ,
            "subCategoryCode":order.sub_code,
            "category": order.category,
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

            "status":
            order.workflow_status,

            "items":
            items,

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
                row.workflow_status

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

    return submit_record(

        module_code="order",

        record_id=order_id,

        submitted_by=submitted_by
    )

def reback_order(

        order_id,

        reback_by=None,

        comments=None
):

    return reback_record(

        module_code="order",

        record_id=order_id,

        user_id=reback_by,

        comments=comments
    )

def reject_order(

        order_id,

        rejected_by=None,

        comments=None
):

    return reject_record(

        module_code="order",

        record_id=order_id,

        user_id=rejected_by,

        comments=comments
    )

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