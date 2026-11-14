"""
Backend test setup.

The tests need a THROWAWAY PostgreSQL database (many queries use Postgres
features, so SQLite is not enough). Point TEST_DATABASE_URL at it:

    TEST_DATABASE_URL=postgresql://user@127.0.0.1:5432/erp_test python -m pytest tests

Safety: the database name must contain "test" — the tests create and drop
every table in it. Without TEST_DATABASE_URL every test is skipped.

Nothing here calls WhatsApp, e-mail, Firebase, Anthropic or Cloudinary:
their credentials are blanked and all outgoing HTTP goes to a dead proxy.
"""

import contextlib
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_DB = os.getenv("TEST_DATABASE_URL", "")

# no real outside services, no scheduler, no secrets from .env
for _name in ("WHATSAPP_TOKEN", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "FIREBASE_CREDENTIALS",
              "ANTHROPIC_API_KEY", "MAIL_APP_PASSWORD", "CLOUDINARY_URL"):
    os.environ[_name] = ""
os.environ["SCHEDULER_MODE"] = "off"
os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-0123456789abcdef")
os.environ.setdefault("LOG_LEVEL", "WARNING")


def _db_name(url):
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


@pytest.fixture(scope="session")
def app():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set — see tests/conftest.py")
    if "test" not in _db_name(TEST_DB).lower():
        pytest.exit(f"Refusing to run: database '{_db_name(TEST_DB)}' does not look like a test database")

    from app.config import Config
    Config.SQLALCHEMY_DATABASE_URI = TEST_DB
    Config.JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    with contextlib.redirect_stdout(io.StringIO()):
        from app import create_app
        flask_app = create_app()
    flask_app.config["TESTING"] = True
    _register_test_routes(flask_app)

    from app.extensions import db
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def _register_test_routes(flask_app):
    """Routes used only by the tests (prefix /__test), registered before any request."""
    from flask import Blueprint
    from app.extensions import db
    from app.models.role import Role
    from app.utils.resilience import breaker

    bp = Blueprint("tests_only", __name__)

    @bp.route("/boom")
    def boom():
        db.session.add(Role(name="must_not_persist"))
        db.session.flush()
        raise ValueError("internal detail that must not leak")

    @bp.route("/ok")
    def ok():
        return {"message": "ok", "data": [1]}

    @bp.route("/ai")
    def ai():
        with breaker("anthropic").protect():
            return {"message": "never", "data": []}

    flask_app.register_blueprint(bp, url_prefix="/__test")


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def admin_headers(app):
    """Token for an admin user (global role "admin")."""
    from flask_jwt_extended import create_access_token
    from app.extensions import db
    from app.models.role import Role
    from app.models.user import User

    with app.app_context():
        role = Role.query.filter_by(name="admin").first() or Role(name="admin")
        db.session.add(role)
        db.session.flush()
        user = User.query.filter_by(email="admin@tests.invalid").first()
        if user is None:
            user = User(username="Test Admin", login_username="test.admin", email="admin@tests.invalid",
                        password_hash="x", mobile="0000000000", wp_mobile="0000000000", emp_code="T0",
                        global_role_id=role.id)
            user.set_password("Test#Pass1")
            db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id), additional_claims={"role": "admin", "permissions": {}})
    return {"Authorization": f"Bearer {token}"}
