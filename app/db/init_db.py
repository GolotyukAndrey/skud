from app.db.session import engine
from app.db.models import Base
from app.db.bootstrap import ensure_default_admin

def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_default_admin()