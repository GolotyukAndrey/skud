from werkzeug.security import generate_password_hash
from app.db.session import SessionLocal
from app.db.models import Admin
from app.config import settings


def ensure_default_admin() -> None:
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(
            Admin.username == settings.DEFAULT_ADMIN_USERNAME
        ).one_or_none()

        if admin is None:
            new_admin = Admin(
                username=settings.DEFAULT_ADMIN_USERNAME,
                password_hash=generate_password_hash(settings.DEFAULT_ADMIN_PASSWORD),
                is_active=True
            )
            db.add(new_admin)
            db.commit()
            print(f"[BOOTSTRAP] Default admin '{settings.DEFAULT_ADMIN_USERNAME}' created")
    finally:
        db.close()