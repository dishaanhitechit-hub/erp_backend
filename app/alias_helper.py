from app.models.workflow_alias import *


def get_approval_module(
        module_code
):

    row = (
        WorkflowModuleAlias.query
        .filter_by(
            module_code=module_code
        )
        .first()
    )

    if row:
        return row.approval_module_code

    return module_code