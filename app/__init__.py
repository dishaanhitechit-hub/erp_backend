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

    from .modules.resources.srn.routes import srn_bp
    app.register_blueprint(srn_bp, url_prefix="/resource/srn")

    from .modules.resources.vendor_billing_grn.routes import bvs_bp
    app.register_blueprint(bvs_bp, url_prefix="/resource/bvs")

    from .modules.resources.vendor_billing_srn.routes import bss_bp
    app.register_blueprint(bss_bp, url_prefix="/resource/bss")

    from .modules.resources.machinery_mgmt.routes import machinery_bp
    app.register_blueprint(machinery_bp, url_prefix="/resource/machinery")

    from .modules.project_mgmt.register.drawing_register.routes import drawing_register_bp
    app.register_blueprint(drawing_register_bp, url_prefix="/project-mgmt/register/drawing-register")

    from .modules.resources.order_projectwork.routes import pw_order_bp
    app.register_blueprint(pw_order_bp, url_prefix="/resource/pw-order")

    from .modules.project.routes import project_bp
    app.register_blueprint(project_bp, url_prefix="/project")

    from .modules.project_mgmt.register.concrete_registry.routes import concrete_registry_bp
    app.register_blueprint(concrete_registry_bp, url_prefix="/project-mgmt/register/concrete-registry")

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