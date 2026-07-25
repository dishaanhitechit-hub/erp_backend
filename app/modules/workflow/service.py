from sqlalchemy import or_

from app.response import res
from app.models.approval_path import ApprovalPath
from app.modules.work_flow import get_approval_module

from app.models.indent_master import IndentMaster
from app.models.orderMaster import OrderMaster
from app.models.grnMaster import GrnMaster
from app.models.ginMaster import GinMaster
from app.models.srnMaster import SrnMaster
from app.models.dcMaster import DcMaster
from app.models.concrete_registry import ConcreteRegistry
from app.models.drawingRegister import DrawingRegister
from app.models.brrMaster import BrrMaster
from app.models.bvsMaster import BvsMaster
from app.models.bssMaster import BssMaster
from app.models.machineryLogBook import MachineryLogBook
from app.models.enquiry_master import EnquiryMaster
from app.models.ORDER_projectwork import ProjectWorkOrderMaster


# ==========================================
# MODULE MAP
# model     : SQLAlchemy model class
# no_field  : document-number attribute name
# dc        : True for DeliveryChallan (dual project_code columns)
# ==========================================

MODULE_MAP = {

    "indent": {
        "model":    IndentMaster,
        "no_field": "indent_no",
    },

    "order": {
        "model":    OrderMaster,
        "no_field": "order_no",
    },

    "goods_received_note": {
        "model":    GrnMaster,
        "no_field": "grn_no",
    },

    "goods_issue_note": {
        "model":    GinMaster,
        "no_field": "gin_no",
    },

    "service_received_note": {
        "model":    SrnMaster,
        "no_field": "srn_no",
    },

    "delivery_challan": {
        "model":    DcMaster,
        "no_field": "dc_no",
        "dc":       True,
    },

    "concrete_registry": {
        "model":    ConcreteRegistry,
        "no_field": "batch_no",
    },

    "drawing_register": {
        "model":    DrawingRegister,
        "no_field": "dr_no",
    },

    "bill_receive_register": {
        "model":    BrrMaster,
        "no_field": "brr_no",
    },

    "billing_by_grn": {
        "model":    BvsMaster,
        "no_field": "bvs_no",
    },

    "billing_by_srn": {
        "model":    BssMaster,
        "no_field": "bss_no",
    },

    "log_sheet": {
        "model":    MachineryLogBook,
        "no_field": "log_book_no",
    },

    "enquiry": {
        "model":    EnquiryMaster,
        "no_field": "enquiry_no",
    },

    "pw_order": {
        "model":    ProjectWorkOrderMaster,
        "no_field": "order_no",
    },

}


# ==========================================
# MY PENDING APPROVALS
# ==========================================

def get_my_pending_approvals(module_code, project_code, user_id):

    try:

        if not project_code:
            return res(
                "Project code missing from token",
                [],
                400
            )

        entry = MODULE_MAP.get(module_code)

        if not entry:
            return res(
                "Invalid module code",
                [],
                400
            )

        approval_code = get_approval_module(module_code)

        # levels where this user is an APPROVER for this project+module
        user_paths = (

            ApprovalPath.query

            .filter_by(

                project_code=project_code,
                module_code=approval_code,
                user_id=user_id,
                path_type="APPROVER"

            )

            .all()

        )

        if not user_paths:
            return res("My pending approvals", [], 200)

        pending_statuses = [
            f"Pending_L{p.level_no}"
            for p in user_paths
        ]

        Model    = entry["model"]
        no_field = entry["no_field"]
        is_dc    = entry.get("dc", False)

        if is_dc:
            project_filter = or_(
                Model.to_project_code   == project_code,
                Model.from_project_code == project_code,
            )
        else:
            project_filter = (
                Model.project_code == project_code
            )

        records = (

            Model.query

            .filter(
                project_filter,
                Model.workflow_status.in_(pending_statuses)
            )

            .order_by(Model.id.desc())

            .all()

        )

        data = []

        for r in records:

            data.append({

                "id":
                r.id,

                "recordNo":
                getattr(r, no_field, None),

                "workflowStatus":
                r.workflow_status,

                "currentLevel":
                r.current_level,

                "createdAt": (
                    r.created_at.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if r.created_at else None
                ),

            })

        return res(
            "My pending approvals",
            data,
            200
        )

    except Exception as e:

        return res(str(e), [], 500)
