from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from app.db.session import SessionLocal
from app.db.models import User, Camera, AccessPoint, AccessEvent
from app.runtime.access_worker_manager import access_worker_manager


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        # --- KPI ---
        users_total = db.query(func.count(User.user_id)).scalar() or 0
        users_active = db.query(func.count(User.user_id)).filter(User.is_active.is_(True)).scalar() or 0

        cameras_total = db.query(func.count(Camera.camera_id)).scalar() or 0
        cameras_active = db.query(func.count(Camera.camera_id)).filter(Camera.is_active.is_(True)).scalar() or 0

        access_points_total = db.query(func.count(AccessPoint.access_point_id)).scalar() or 0
        access_points_active = (
            db.query(func.count(AccessPoint.access_point_id))
            .filter(AccessPoint.is_active.is_(True))
            .scalar()
            or 0
        )

        time_from = datetime.utcnow() - timedelta(hours=24)
        events_24h = (
            db.query(func.count(AccessEvent.event_id))
            .filter(AccessEvent.occurred_at >= time_from)
            .scalar()
            or 0
        )

        last_event = db.query(AccessEvent).order_by(desc(AccessEvent.occurred_at)).first()
        last_event_time = last_event.occurred_at if last_event else None

        stats = {
            "users_total": users_total,
            "users_active": users_active,
            "cameras_total": cameras_total,
            "cameras_active": cameras_active,
            "access_points_total": access_points_total,
            "access_points_active": access_points_active,
            "events_24h": events_24h,
            "last_event_time": last_event_time,
        }

        points = (
            db.query(AccessPoint)
            .filter(AccessPoint.is_active.is_(True))
            .order_by(AccessPoint.name)
            .all()
        )

        ap_rows = []
        for p in points:
            st = access_worker_manager.get_status(p.access_point_id)

            last_ev = (
                db.query(AccessEvent)
                .filter(AccessEvent.access_point_id == p.access_point_id)
                .order_by(desc(AccessEvent.occurred_at))
                .first()
            )

            ap_rows.append({
                "access_point_id": p.access_point_id,
                "name": p.name,
                "zone_name": p.zone.name if getattr(p, "zone", None) else "—",
                "worker_running": bool(st.running),
                "last_decision": last_ev.decision if last_ev else "",
                "last_subject": (
                    last_ev.user.full_name if last_ev and last_ev.user else "UNKNOWN"
                ) if last_ev else "",
                "last_time": last_ev.occurred_at if last_ev else None,
            })

        last_events = (
            db.query(AccessEvent)
            .order_by(desc(AccessEvent.occurred_at))
            .limit(10)
            .all()
        )

        return render_template(
            "dashboard.html",
            admin=current_user,
            stats=stats,
            ap_rows=ap_rows,
            last_events=last_events,
            active_nav="dashboard",
        )
    finally:
        db.close()