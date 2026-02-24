from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import desc

from app.db.session import SessionLocal
from app.db.models import AccessEvent, AccessPoint, User

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.route("/")
@login_required
def list_events():
    # Фильтры
    decision = request.args.get("decision", "").strip()  # ALLOW/DENY/UNKNOWN/empty
    access_point_id = request.args.get("access_point_id", "").strip()
    q = request.args.get("q", "").strip()  # поиск по ФИО (если user есть)
    days = request.args.get("days", "1").strip()  # по умолчанию за сутки

    try:
        days_int = max(1, min(30, int(days)))
    except ValueError:
        days_int = 1

    time_from = datetime.utcnow() - timedelta(days=days_int)

    db = SessionLocal()
    try:
        points = db.query(AccessPoint).order_by(AccessPoint.name).all()

        query = (
            db.query(AccessEvent)
            .join(AccessPoint)
            .outerjoin(User)  # user может быть NULL
            .filter(AccessEvent.occurred_at >= time_from)
        )

        if decision in ("ALLOW", "DENY", "UNKNOWN"):
            query = query.filter(AccessEvent.decision == decision)

        if access_point_id.isdigit():
            query = query.filter(AccessEvent.access_point_id == int(access_point_id))

        if q:
            # если user_id NULL — событие всё равно покажется, но не совпадёт по фильтру
            query = query.filter(User.full_name.ilike(f"%{q}%"))

        events = query.order_by(desc(AccessEvent.occurred_at)).limit(500).all()

        return render_template(
            "events_list.html",
            events=events,
            points=points,
            filters={
                "decision": decision,
                "access_point_id": access_point_id,
                "q": q,
                "days": str(days_int),
            },
            active_nav="events",
        )
    finally:
        db.close()