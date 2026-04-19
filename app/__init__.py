from flask import Flask
from .config import Config
from .extensions import db, jwt, bcrypt, migrate
from app import models
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    CORS(app)
    app.config.from_object(Config)

    # init extensions
    db.init_app(app)
    jwt.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)

    # register routes
    from .modules.auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from .modules.setting.routes import setting_bp
    app.register_blueprint(setting_bp, url_prefix="/setting")
    return app