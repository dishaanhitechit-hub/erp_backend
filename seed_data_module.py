from app.extensions import db
from app.models.main_module import MainModule
from app.models.sub_module import SubModule
from app.models.feature_page import FeaturePage
#
# seed_data = {
#
# "Settings":{
#     "Company Details":"/settings/company-details",
#     "User ID & Password":"/settings/user-id-password",
#     "Project Code":"/settings/project-code",
#     "Roles & User Assignment":"/settings/role-designation",
#     "Approval Path Line & User":"/settings/approval-path"
# },
#
# "Master":{
#     "Ledger Code":"/master/ledger-code",
#     "Item Code":"/master/item-code",
#     "Asset Code":"/master/asset-code",
#     "Unit":"/master/unit",
#     "Cost Center Code":"/master/cc-code",
#     "Category & Group":"/master/category-group"
# },
#
# "Resource Management":{
#
#     "Procurement":{
#         "Indent":"/resource-management/procurement/indent",
#         "Enquiry":"/resource-management/procurement/enquiry",
#         "Order":"/resource-management/procurement/order"
#     },
#
#     "Material Management":{
#         "Goods Received Note":
#             "/resource-management/material/grn",
#
#         "Goods Issue Note":
#             "/resource-management/material/gin",
#
#         "Stock Report":
#             "/resource-management/material/stock-report"
#     },
#
#     "Manpower Management":{
#         "Manpower ID":
#             "/resource-management/manpower/id",
#
#         "Attendance":
#             "/resource-management/manpower/attendance"
#     },
#
#     "Machinery Management":{
#         "Log Sheet":
#             "/resource-management/machinery/log-sheet",
#
#         "Machinery Stock Summary":
#             "/resource-management/machinery/stock",
#
#         "Monthly Rent Calculation":
#             "/resource-management/machinery/rent"
#     },
#
#     "Vendor Billing":{
#         "Billing by GRN":
#             "/resource-management/vendor-billing/grn",
#
#         "Billing by SRN":
#             "/resource-management/vendor-billing/srn"
#     }
# },
#
# "Asset Management":{
#
#     "Asset Indent":
#         "/asset-management/indent",
#
#     "Allocation":
#         "/asset-management/allocation",
#
#     "Asset ID Creation":
#         "/asset-management/asset-id",
#
#     "Asset Stock Report":
#         "/asset-management/stock-report"
# },
#
# "Project Management":{
#
#     "Order & BOQ":
#         "/project-management/order-boq",
#
#     "Budget & Costing":
#         "/project-management/budget",
#
#     "Planning":{
#
#         "Monthly Planning":
#             "/project-management/planning/monthly",
#
#         "Daily Progress Report":
#             "/project-management/planning/dpr",
#
#         "Reconciliation":
#             "/project-management/planning/reconciliation"
#     },
#
#     "Customer Billing":{
#
#         "Certified Bill":
#             "/project-management/customer-billing/certified",
#
#         "Hold / Amend Pending":
#             "/project-management/customer-billing/pending",
#
#         "Work In Progress":
#             "/project-management/customer-billing/wip"
#     },
#
#     "Register":{
#
#         "Drawing Register":
#             "/project-management/register/drawing",
#
#         "BBS Register":
#             "/project-management/register/bbs",
#
#         "Concrete Register":
#             "/project-management/register/concrete"
#     },
#
#     "Tool Kit":{
#
#         "BBS":
#             "/project-management/toolkit/bbs",
#
#         "Measurement":
#             "/project-management/toolkit/measurement",
#
#         "Abstract":
#             "/project-management/toolkit/abstract",
#
#         "C. Abstract":
#             "/project-management/toolkit/c-abstract"
#     }
# },
#
# "Finance Management":{
#
#     "Account":{
#
#         "Sale":
#             "/finance-management/account/sale",
#
#         "Purchases":
#             "/finance-management/account/purchases",
#
#         "Receipt":
#             "/finance-management/account/receipt",
#
#         "Payment":
#             "/finance-management/account/payment",
#
#         "Contra":
#             "/finance-management/account/contra",
#
#         "Debit Note":
#             "/finance-management/account/debit-note",
#
#         "Credit Note":
#             "/finance-management/account/credit-note",
#
#         "Journal":
#             "/finance-management/account/journal"
#     },
#
#     "Finance Report":{
#
#         "Profit & Loss":
#             "/finance-management/report/pnl",
#
#         "Balance Sheet":
#             "/finance-management/report/balance-sheet",
#
#         "Cash Flow":
#             "/finance-management/report/cash-flow",
#
#         "GST Reconciliation":
#             "/finance-management/report/gst",
#
#         "Vendor Liability":
#             "/finance-management/report/vendor-liability",
#
#         "Ledger View":
#             "/finance-management/report/ledger"
#     }
# },
#
# "HR Management":{
#
#     "Employee Management":
#         "/hr-management/employee",
#
#     "Administration":
#         "/hr-management/admin",
#
#     "Circular":
#         "/hr-management/circular",
#
#     "Notice":
#         "/hr-management/notice"
# },
#
# "Task Management":{
#
#     "New Task":
#         "/task-management/new",
#
#     "Closing Task":
#         "/task-management/closing",
#
#     "To Do List":
#         "/task-management/todo"
# }
#
# }
#
#
#
# def make_page_code(text):
#
#     return (
#         text.lower()
#         .replace("&", "and")
#         .replace(".", "")
#         .replace("/", "_")
#         .replace("-", "_")
#         .replace(" ", "_")
#     )
#
# def seed_modules():
#
#     for module_name, children in seed_data.items():
#
#         # ===============================
#         # MAIN MODULE
#         # ===============================
#
#         existing_module = (
#             MainModule.query
#             .filter_by(
#                 module_name=module_name
#             )
#             .first()
#         )
#
#         if existing_module:
#
#             main = existing_module
#
#         else:
#
#             main = MainModule(
#                 module_name=module_name
#             )
#
#             db.session.add(main)
#
#             db.session.flush()
#
#         # ===============================
#         # CHILD LOOP
#         # ===============================
#
#         for key, value in children.items():
#
#             # =====================================
#             # SUBMODULE WITH INNER PAGES
#             # Procurement → Indent
#             # =====================================
#
#             if isinstance(value, dict):
#
#                 existing_sub = (
#                     SubModule.query
#                     .filter_by(
#                         main_module_id=main.id,
#                         submodule_name=key
#                     )
#                     .first()
#                 )
#
#                 if existing_sub:
#
#                     sub = existing_sub
#
#                 else:
#
#                     sub = SubModule(
#                         main_module_id=main.id,
#                         submodule_name=key
#                     )
#
#                     db.session.add(sub)
#
#                     db.session.flush()
#
#                 for page_name, route in value.items():
#
#                     page_code = (
#                         make_page_code(
#                             page_name
#                         )
#                     )
#
#                     exists = (
#                         FeaturePage.query
#                         .filter_by(
#                             page_code=page_code
#                         )
#                         .first()
#                     )
#
#                     if exists:
#                         continue
#
#                     page = FeaturePage(
#
#                         submodule_id=sub.id,
#
#                         page_name=page_name,
#
#                         page_code=page_code,
#
#                         route_path=route,
#
#                         is_menu_visible=True
#                     )
#
#                     db.session.add(page)
#
#             # =====================================
#             # DIRECT PAGE
#             # Settings → Company Details
#             # =====================================
#
#             else:
#
#                 existing_sub = (
#                     SubModule.query
#                     .filter_by(
#                         main_module_id=main.id,
#                         submodule_name=key
#                     )
#                     .first()
#                 )
#
#                 if existing_sub:
#
#                     sub = existing_sub
#
#                 else:
#
#                     sub = SubModule(
#
#                         main_module_id=main.id,
#
#                         submodule_name=key
#                     )
#
#                     db.session.add(sub)
#
#                     db.session.flush()
#
#                 page_code = (
#                     make_page_code(
#                         key
#                     )
#                 )
#
#                 exists = (
#                     FeaturePage.query
#                     .filter_by(
#                         page_code=page_code
#                     )
#                     .first()
#                 )
#
#                 if exists:
#                     continue
#
#                 page = FeaturePage(
#
#                     submodule_id=sub.id,
#
#                     page_name=key,
#
#                     page_code=page_code,
#
#                     route_path=value,
#
#                     is_menu_visible=True
#                 )
#
#                 db.session.add(page)
#
#     db.session.commit()
#
# print("starting seed...")
#
#
#
#
# # seed_permission_action.py

from app import create_app
from app.extensions import db
from app.models.permission_action import PermissionAction


actions = [
    "VIEW",
    "EDIT"
]


def seed_permission_actions():

    for action in actions:

        exists = (
            PermissionAction.query
            .filter_by(
                action_name=action
            )
            .first()
        )

        if exists:
            continue

        permission = (
            PermissionAction(
                action_name=action
            )
        )

        db.session.add(
            permission
        )

    db.session.commit()

    print(
        "Permission actions seeded"
    )

from app import create_app
app=create_app()

with app.app_context():

    seed_permission_actions()

#
# app = create_app()
#
# with app.app_context():
#     seed_modules()

print("seed completed")