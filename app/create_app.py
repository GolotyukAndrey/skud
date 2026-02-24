from flask import Flask
from flask_login import LoginManager

from app.config import settings
from app.db.init_db import init_db
from app.web.routes_auth import auth_bp
from app.web.routes_dashboard import dashboard_bp
from app.web.routes_users import users_bp
from app.web.routes_biometry import biometry_bp
from app.web.routes_cameras import cameras_bp
from app.web.routes_zones import zones_bp
from app.web.routes_roles import roles_bp
from app.web.routes_permissions import permissions_bp
from app.web.routes_control_units import control_units_bp
from app.web.routes_access_points import access_points_bp
from app.web.routes_events import events_bp
from app.web.routes_debug import debug_bp
from app.web.routes_stream import stream_bp
from app.db.models import Admin
from app.db.session import SessionLocal


login_manager = LoginManager()
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(admin_id: str):
    db = SessionLocal()
    try:
        return db.get(Admin, int(admin_id))
    finally:
        db.close()


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static"
    )

    app.config["SECRET_KEY"] = "dev-secret-key-change-later"

    init_db()

    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(biometry_bp)
    app.register_blueprint(cameras_bp)
    app.register_blueprint(zones_bp)
    app.register_blueprint(roles_bp)
    app.register_blueprint(permissions_bp)
    app.register_blueprint(control_units_bp)
    app.register_blueprint(access_points_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(debug_bp)
    app.register_blueprint(stream_bp)

    return app