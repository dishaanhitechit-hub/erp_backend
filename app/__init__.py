from flask import Flask
from .config import Config
from .extensions import db, jwt, bcrypt, migrate
# from .FUN.socket import socketio
# from .FUN.error_sound import register_error_sound_handlers

from flask_cors import CORS
from .middleware.maintenance import register_maintenance_middleware

def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
    app.config.from_object(Config)

    # init extensions
    db.init_app(app)
    jwt.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)

    # maintenance model — must be imported so Alembic detects the table
    from .models import maintenance_txn  # noqa
    from .models import manpower  # noqa — registers ManpowerWorker with Alembic
    from .models import dlrMaster  # noqa — registers DlrMaster, DlrItem with Alembic
    from .models import pmMaster  # noqa — registers PMMaster, PMServiceHistory, PMServiceSchedule

    # maintenance middleware
    register_maintenance_middleware(app)
    # socketio.init_app(app)

    # FUN: error sound on every error
    # register_error_sound_handlers(app)

    # register routes
    from .modules.auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from .modules.setting.routes import setting_bp
    app.register_blueprint(setting_bp, url_prefix="/setting")

    from .modules.company.routes import company_bp
    app.register_blueprint(company_bp, url_prefix="/compny")

    from .modules.master.routes import master_bp
    app.register_blueprint(master_bp, url_prefix="/master")

    from .modules.resources.indent.routes import indent_bp
    app.register_blueprint(indent_bp, url_prefix="/resource/indent")

    from .modules.resources.enquiry.routes import enquiry_bp
    app.register_blueprint(enquiry_bp, url_prefix="/resource/enquiry")
    from .modules.resources.order.routes import order_bp
    app.register_blueprint(order_bp, url_prefix="/resource/order")

    from .modules.resources.grn.routes import grn_bp
    app.register_blueprint(grn_bp, url_prefix="/resource/grn")

    from .modules.resources.gin.routes import gin_bp
    app.register_blueprint(gin_bp, url_prefix="/resource/gin")

    from .modules.resources.stock.routes import stock_bp
    app.register_blueprint(stock_bp, url_prefix="/resource/stock")

    from .modules.resources.srn.routes import srn_bp
    app.register_blueprint(srn_bp, url_prefix="/resource/srn")

    from .modules.resources.vendor_billing_grn.routes import bvs_bp
    app.register_blueprint(bvs_bp, url_prefix="/resource/bvs")

    from .modules.resources.vendor_billing_srn.routes import bss_bp
    app.register_blueprint(bss_bp, url_prefix="/resource/bss")

    from .modules.resources.machinery_mgmt.routes import machinery_bp
    app.register_blueprint(machinery_bp, url_prefix="/resource/machinery")

    from .modules.resources.dc.routes import dc_bp
    app.register_blueprint(dc_bp, url_prefix="/resource/dc")

    from .modules.resources.manpower.routes import manpower_bp
    app.register_blueprint(manpower_bp, url_prefix="/resource/manpower")

    from .modules.resources.dlr.routes import dlr_bp
    app.register_blueprint(dlr_bp, url_prefix="/resource/dlr")

    from .modules.resources.machinery_mgmt.pm_id_routes import pm_id_bp
    app.register_blueprint(pm_id_bp, url_prefix="/resource/machinery/pm-id")

    from .modules.resources.machinery_mgmt.service_history_routes import service_history_bp
    app.register_blueprint(service_history_bp, url_prefix="/resource/machinery/service-history")

    from .modules.resources.machinery_mgmt.service_schedule_routes import service_schedule_bp
    app.register_blueprint(service_schedule_bp, url_prefix="/resource/machinery/service-schedule")

    from .modules.project_mgmt.register.drawing_register.routes import drawing_register_bp
    app.register_blueprint(drawing_register_bp, url_prefix="/project-mgmt/register/drawing-register")

    from .modules.resources.order_projectwork.routes import pw_order_bp
    app.register_blueprint(pw_order_bp, url_prefix="/resource/pw-order")

    from .modules.project.routes import project_bp
    app.register_blueprint(project_bp, url_prefix="/project")

    from .modules.project_mgmt.register.concrete_registry.routes import concrete_registry_bp
    app.register_blueprint(concrete_registry_bp, url_prefix="/project-mgmt/register/concrete-registry")

    from .modules.search.routes import search_bp
    app.register_blueprint(search_bp, url_prefix="/search")

    from .modules.billing.bill_receive_register.routes import brr_bp
    app.register_blueprint(brr_bp, url_prefix="/billing/brr")

    from .modules.billing.brr_billing.routes import brb_bp
    app.register_blueprint(brb_bp, url_prefix="/billing/brb")

    from .modules.workflow.routes import workflow_bp
    app.register_blueprint(workflow_bp, url_prefix="/workflow")

    from .modules.resources.batching_plant.routes import batching_bp
    app.register_blueprint(batching_bp, url_prefix="/resource/batching")

    from .models import batchingPlant  # noqa — registers BatchingPlantMaster with Alembic

    from .modules.project_mgmt.register.bbs_register.routes import bbs_register_bp
    app.register_blueprint(bbs_register_bp, url_prefix="/project-mgmt/register/bbs-register")

    from .models import bbsRegister  # noqa — registers BbsRegister with Alembic

    from .modules.project_mgmt.register.hindrance_register.routes import hindrance_register_bp
    app.register_blueprint(hindrance_register_bp, url_prefix="/project-mgmt/register/hindrance-register")

    from .models import hindranceRegister  # noqa — registers HindranceRegister with Alembic

    from .modules.project_mgmt.custom_billing.billing.routes import billing_bp
    app.register_blueprint(billing_bp, url_prefix="/project-mgmt/billing")

    from .modules.project_mgmt.custom_billing.og_sale_order.routes import og_sale_order_bp
    app.register_blueprint(og_sale_order_bp, url_prefix="/project-mgmt/og-sale-order")

    from .models import billingMaster  # noqa — registers BillingMaster, BillingItem with Alembic
    from .models import ogSaleOrder    # noqa — registers OgSaleOrderMaster, OgSaleOrderItem with Alembic

    from .modules.finance.sale_bill.routes import sale_bill_bp
    app.register_blueprint(sale_bill_bp, url_prefix="/finance/sale-bill")

    from .models import saleBill  # noqa — registers SaleBillMaster, SaleBillItem, SaleBillGst with Alembic

    from .modules.finance.purchase_bill.routes import purchase_bill_bp
    app.register_blueprint(purchase_bill_bp, url_prefix="/finance/purchase-bill")

    from .models import purchaseBill  # noqa — registers PurchaseBillMaster, PurchaseBillItem, PurchaseBillGst with Alembic

    from .modules.finance.purchase_voucher.routes import purchase_voucher_bp
    app.register_blueprint(purchase_voucher_bp, url_prefix="/finance/purchase-voucher")

    from .models import purchaseVoucher  # noqa — registers PurchaseVoucherMaster, PurchaseVoucherItem, PurchaseVoucherGst with Alembic

    from .modules.finance.sale_receipt.routes import sale_receipt_bp
    app.register_blueprint(sale_receipt_bp, url_prefix="/finance/sale-receipt")

    from .models import saleReceipt  # noqa — registers SaleReceiptMaster, SaleReceiptItem, SaleReceiptGst with Alembic

    # from .modules.communication.communication_routes import comm_bp
    # app.register_blueprint(comm_bp, url_prefix="/comm")

    # from .modules.communication.frontend_route import frontend_bp
    # app.register_blueprint(frontend_bp)

    # from .modules.tracking.presence_routes import presence_bp
    # from .modules.tracking.activity_routes import activity_bp
    # app.register_blueprint(presence_bp, url_prefix="/tracking")
    # app.register_blueprint(activity_bp, url_prefix="/tracking")

    print("JWT_SECRET_KEY:", app.config.get("JWT_SECRET_KEY"))
    print("JWT_ACCESS_TOKEN_EXPIRES:", app.config.get("JWT_ACCESS_TOKEN_EXPIRES"))

    return app