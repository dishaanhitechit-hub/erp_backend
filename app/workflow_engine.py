from datetime import datetime
from app.response import res
from app.extensions import db
from app.modules.work_flow import *
from  models.indent_master import IndentMaster
from models.orderMaster import OrderMaster

MODEL_MAP={

    "indent":IndentMaster,

    "order":OrderMaster

}

def submit_record(
        module_code,
        record_id,
        submitted_by=None
):

    try:

        Model=MODEL_MAP.get(
            module_code
        )

        if not Model:

            return res(
                "Invalid module",
                [],
                400
            )

        record=Model.query.get(
            record_id
        )

        if not record:

            return res(
                f"{module_code} not found",
                [],
                404
            )


        if record.workflow_status not in [

            "Draft",

            "Reback"

        ]:

            return res(
                "Already submitted",
                [],
                400
            )


        if module_code=="order":

            if not record.items:

                return res(
                    "Order has no items",
                    [],
                    400
                )

        elif module_code=="indent":

            if not record.indent_items:

                return res(
                    "Indent has no items",
                    [],
                    400
                )


        if record.workflow_status=="Reback":

            record.current_level=0


        first_level=get_first_approver(

            record.project_code,

            module_code
        )


        if not first_level:

            record.workflow_status=(
                "Approved"
            )

            record.locked=True

            record.approved_by=(
                submitted_by
            )

            record.submitted_at=(
                datetime.utcnow()
            )

            record.final_approved_at=(
                datetime.utcnow()
            )

        else:

            record.workflow_status=(

                f"Pending_L"

                f"{first_level.level_no}"

            )

            record.current_level=(
                first_level.level_no
            )

            record.locked=True

            record.submitted_at=(
                datetime.utcnow()
            )


        create_history(

            project_code=
            record.project_code,

            module_code=
            module_code,

            record_id=
            record.id,

            level_no=
            record.current_level,

            action=
            "SUBMIT",

            action_by=
            submitted_by

        )


        db.session.commit()


        return res(

            f"{module_code} submitted",

            {

                "id":
                record.id,

                "workflowStatus":
                record.workflow_status

            },

            200
        )

    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )


def reback_record(
        module_code,
        record_id,
        user_id,
        comments
):

    try:

        Model=MODEL_MAP[
            module_code
        ]

        record=Model.query.get(
            record_id
        )

        if not record:

            return res(
                "Not found",
                [],
                404
            )


        if not record.workflow_status.startswith(
            "Pending"
        ):

            return res(
                "Not pending",
                [],
                400
            )


        if not comments:

            return res(
                "Comments required",
                [],
                400
            )


        allowed=is_current_approver(

            record.project_code,

            module_code,

            record.current_level,

            user_id
        )


        if not allowed:

            return res(
                "Not current approver",
                [],
                403
            )


        record.workflow_status=(
            "Reback"
        )

        record.locked=False

        record.correction_sent_at=(
            datetime.utcnow()
        )


        create_history(

            project_code=
            record.project_code,

            module_code=
            module_code,

            record_id=
            record.id,

            level_no=
            record.current_level,

            action=
            "REBACK",

            action_by=
            user_id,

            comments=
            comments
        )


        db.session.commit()

        return res(
            "Sent back",
            [],
            200
        )


    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )

def reject_record(
        module_code,
        record_id,
        user_id=None,
        comments=None
):

    try:

        Model=MODEL_MAP.get(
            module_code
        )

        if not Model:

            return res(
                "Invalid module",
                [],
                400
            )

        record=Model.query.get(
            record_id
        )

        if not record:

            return res(
                f"{module_code} not found",
                [],
                404
            )

        # ==========================================
        # ONLY PENDING CAN REJECT
        # ==========================================

        if not record.workflow_status.startswith(
            "Pending"
        ):

            return res(
                f"{module_code} not pending",
                [],
                400
            )

        # ==========================================
        # COMMENTS REQUIRED
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

        allowed=is_current_approver(

            record.project_code,

            module_code,

            record.current_level,

            user_id
        )

        if not allowed:

            return res(
                "You are not current approver",
                [],
                403
            )

        # ==========================================
        # UPDATE STATUS
        # ==========================================

        record.workflow_status=(
            "Rejected"
        )

        record.locked=True

        record.rejected_at=(
            datetime.utcnow()
        )

        record.rejected_by=(
            user_id
        )

        record.status=(
            "Inactive"
        )

        record.updated_by=(
            user_id
        )

        record.updated_at=(
            datetime.utcnow()
        )

        # ==========================================
        # HISTORY
        # ==========================================

        create_history(

            project_code=
            record.project_code,

            module_code=
            module_code,

            record_id=
            record.id,

            level_no=
            record.current_level,

            action=
            "REJECT",

            action_by=
            user_id,

            comments=
            comments
        )

        db.session.commit()

        return res(

            f"{module_code} rejected successfully",

            {

                "id":
                record.id,

                "workflowStatus":
                record.workflow_status

            },

            200
        )

    except Exception as e:

        db.session.rollback()

        return res(
            str(e),
            [],
            500
        )