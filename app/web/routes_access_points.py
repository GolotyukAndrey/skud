from __future__ import annotations

import requests

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from app.db.session import SessionLocal
from app.db.models import AccessPoint, Zone, Camera, ControlUnit, AccessEvent

from app.core.recognition import compute_embedding_from_bgr, match_user_by_embedding
from app.core.decision import decide_access_for_user
from app.runtime.camera_manager import camera_manager
from app.runtime.access_worker_manager import access_worker_manager


access_points_bp = Blueprint("access_points", __name__, url_prefix="/access-points")


@access_points_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        points = db.query(AccessPoint).order_by(AccessPoint.name).all()
        return render_template(
            "access_points_list.html",
            points=points,
            active_nav="access_points",
            page_title="Точки доступа",
            page_subtitle="1 камера = 1 точка доступа. Каждая точка привязана к зоне и (опционально) исполнительному устройству.",
        )
    finally:
        db.close()


@access_points_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        zones = db.query(Zone).order_by(Zone.name).all()
        cameras = db.query(Camera).order_by(Camera.name).all()
        control_units = db.query(ControlUnit).order_by(ControlUnit.name).all()

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            zone_id = request.form.get("zone_id", "").strip()
            camera_id = request.form.get("camera_id", "").strip()
            control_unit_id = request.form.get("control_unit_id", "").strip()
            is_active = request.form.get("is_active") == "on"

            if not name or not zone_id.isdigit() or not camera_id.isdigit():
                flash("Заполните имя, зону и камеру.", "danger")
                return render_template(
                    "access_point_form.html",
                    point=None,
                    zones=zones,
                    cameras=cameras,
                    control_units=control_units,
                    active_nav="access_points",
                    page_title="Новая точка доступа",
                    page_subtitle="Создание точки доступа",
                )

            zid = int(zone_id)
            cid = int(camera_id)
            cuid = int(control_unit_id) if control_unit_id.isdigit() else None

            if not db.get(Zone, zid):
                flash("Выбранная зона не найдена", "danger")
                return render_template("access_point_form.html", point=None, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")
            if not db.get(Camera, cid):
                flash("Выбранная камера не найдена", "danger")
                return render_template("access_point_form.html", point=None, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")
            if cuid is not None and not db.get(ControlUnit, cuid):
                flash("Выбранное исполнительное устройство не найдено", "danger")
                return render_template("access_point_form.html", point=None, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")

            point = AccessPoint(
                name=name,
                zone_id=zid,
                camera_id=cid,
                control_unit_id=cuid,
                is_active=is_active,
            )
            db.add(point)

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя создать точку доступа: нарушено ограничение целостности.", "danger")
                return render_template(
                    "access_point_form.html",
                    point=None,
                    zones=zones,
                    cameras=cameras,
                    control_units=control_units,
                    active_nav="access_points",
                    page_title="Новая точка доступа",
                    page_subtitle="Создание точки доступа",
                )

            flash("Точка доступа создана", "success")
            return redirect(url_for("access_points.list"))

        return render_template(
            "access_point_form.html",
            point=None,
            zones=zones,
            cameras=cameras,
            control_units=control_units,
            active_nav="access_points",
            page_title="Новая точка доступа",
            page_subtitle="Создание точки доступа",
        )
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/edit", methods=["GET", "POST"])
@login_required
def edit(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        zones = db.query(Zone).order_by(Zone.name).all()
        cameras = db.query(Camera).order_by(Camera.name).all()
        control_units = db.query(ControlUnit).order_by(ControlUnit.name).all()

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            zone_id = request.form.get("zone_id", "").strip()
            camera_id = request.form.get("camera_id", "").strip()
            control_unit_id = request.form.get("control_unit_id", "").strip()
            is_active = request.form.get("is_active") == "on"

            if not name or not zone_id.isdigit() or not camera_id.isdigit():
                flash("Заполните имя, зону и камеру.", "danger")
                return render_template(
                    "access_point_form.html",
                    point=point, zones=zones, cameras=cameras, control_units=control_units,
                    active_nav="access_points",
                    page_title="Редактирование точки доступа",
                    page_subtitle="Изменение параметров точки доступа",
                )

            zid = int(zone_id)
            cid = int(camera_id)
            cuid = int(control_unit_id) if control_unit_id.isdigit() else None

            if not db.get(Zone, zid):
                flash("Выбранная зона не найдена", "danger")
                return render_template("access_point_form.html", point=point, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")
            if not db.get(Camera, cid):
                flash("Выбранная камера не найдена", "danger")
                return render_template("access_point_form.html", point=point, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")
            if cuid is not None and not db.get(ControlUnit, cuid):
                flash("Выбранное исполнительное устройство не найдено", "danger")
                return render_template("access_point_form.html", point=point, zones=zones, cameras=cameras, control_units=control_units, active_nav="access_points")

            point.name = name
            point.zone_id = zid
            point.camera_id = cid
            point.control_unit_id = cuid
            point.is_active = is_active

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя сохранить изменения: нарушено ограничение целостности.", "danger")
                return render_template(
                    "access_point_form.html",
                    point=point, zones=zones, cameras=cameras, control_units=control_units,
                    active_nav="access_points",
                    page_title="Редактирование точки доступа",
                    page_subtitle="Изменение параметров точки доступа",
                )

            flash("Изменения сохранены", "success")
            return redirect(url_for("access_points.list"))

        return render_template(
            "access_point_form.html",
            point=point,
            zones=zones,
            cameras=cameras,
            control_units=control_units,
            active_nav="access_points",
            page_title="Редактирование точки доступа",
            page_subtitle="Изменение параметров точки доступа",
        )
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/delete", methods=["POST"])
@login_required
def delete(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        db.delete(point)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Нельзя удалить точку доступа: есть связанные данные (например, события). Лучше отключите её.", "danger")
            return redirect(url_for("access_points.list"))

        flash("Точка доступа удалена", "success")
        return redirect(url_for("access_points.list"))
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/monitor")
@login_required
def monitor(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        events = (
            db.query(AccessEvent)
            .filter(AccessEvent.access_point_id == point.access_point_id)
            .order_by(desc(AccessEvent.occurred_at))
            .limit(30)
            .all()
        )
        last_event = events[0] if events else None

        worker_status = access_worker_manager.get_status(point.access_point_id)

        return render_template(
            "access_point_monitor.html",
            point=point,
            events=events,
            last_event=last_event,
            worker_status=worker_status,
            active_nav="access_points",
            page_title=f"Мониторинг: {point.name}",
            page_subtitle="Текущее состояние точки доступа + live-видео + последние события",
        )
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/auto/start", methods=["POST"])
@login_required
def auto_start(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        access_worker_manager.start(point.access_point_id)

        if point.camera and point.camera.is_active:
            camera_manager.ensure_started(
                key=point.access_point_id,
                source_type=point.camera.source_type,
                source=point.camera.source,
            )

        flash("Автообработка запущена", "success")
        return redirect(url_for("access_points.monitor", point_id=point.access_point_id))
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/auto/stop", methods=["POST"])
@login_required
def auto_stop(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        access_worker_manager.stop(point.access_point_id)
        flash("Автообработка остановлена", "success")
        return redirect(url_for("access_points.monitor", point_id=point.access_point_id))
    finally:
        db.close()


def _send_control_command(point: AccessPoint, cmd: str) -> tuple[bool, str]:
    if not point.control_unit:
        return False, "У точки доступа не назначено исполнительное устройство."

    unit = point.control_unit

    if not unit.is_active:
        return False, "Исполнительное устройство неактивно."

    if unit.unit_type == "stub":
        return True, f"Команда '{cmd}' отправлена (STUB)."

    if unit.unit_type == "http":
        if not unit.endpoint:
            return False, "У HTTP-устройства не задан endpoint."
        try:
            url = unit.endpoint.rstrip("/") + f"/{cmd}"
            r = requests.post(url, timeout=2.0)
            if 200 <= r.status_code < 300:
                return True, f"Команда '{cmd}' отправлена (HTTP {r.status_code})."
            return False, f"HTTP ошибка {r.status_code} при отправке команды."
        except Exception as e:
            return False, f"Не удалось отправить HTTP-команду: {e}"

    return False, f"Неизвестный тип устройства: {unit.unit_type}"


@access_points_bp.route("/<int:point_id>/manual/open", methods=["POST"])
@login_required
def manual_open(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        ok, msg = _send_control_command(point, "open")
        flash(msg, "success" if ok else "danger")

        device = point.control_unit.name if point.control_unit else "—"
        details = f"manual | действие=open | устройство={device} | результат={'ok' if ok else 'fail'}"
        if msg:
            details += f" | сообщение={msg}"

        ev = AccessEvent(
            access_point_id=point.access_point_id,
            user_id=None,
            decision="ALLOW" if ok else "DENY",
            match_score=None,
            details=details,
        )
        db.add(ev)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Не удалось записать событие ручного открытия (IntegrityError).", "danger")

        return redirect(url_for("access_points.monitor", point_id=point.access_point_id))
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/manual/deny", methods=["POST"])
@login_required
def manual_deny(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        ok, msg = _send_control_command(point, "deny")
        flash(msg, "success" if ok else "danger")

        device = point.control_unit.name if point.control_unit else "—"
        details = f"manual | действие=deny | устройство={device} | результат={'ok' if ok else 'fail'}"
        if msg:
            details += f" | сообщение={msg}"

        ev = AccessEvent(
            access_point_id=point.access_point_id,
            user_id=None,
            decision="DENY",
            match_score=None,
            details=details,
        )
        db.add(ev)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Не удалось записать событие ручного запрета (IntegrityError).", "danger")

        return redirect(url_for("access_points.monitor", point_id=point.access_point_id))
    finally:
        db.close()


@access_points_bp.route("/<int:point_id>/snapshot-check", methods=["POST"])
@login_required
def snapshot_check(point_id: int):
    db = SessionLocal()
    try:
        point = db.get(AccessPoint, point_id)
        if not point:
            flash("Точка доступа не найдена", "danger")
            return redirect(url_for("access_points.list"))

        if not point.camera or not point.camera.is_active:
            flash("У точки доступа нет активной камеры.", "danger")
            return redirect(url_for("access_points.monitor", point_id=point.access_point_id))

        camera_manager.ensure_started(
            key=point.access_point_id,
            source_type=point.camera.source_type,
            source=point.camera.source,
        )

        frame = camera_manager.get_latest_frame(point.access_point_id)
        if frame is None:
            flash("Кадр ещё не получен от камеры. Подождите 1–2 секунды и повторите.", "danger")
            return redirect(url_for("access_points.monitor", point_id=point.access_point_id))

        try:
            probe_emb = compute_embedding_from_bgr(frame)
        except ValueError as e:
            ev = AccessEvent(
                access_point_id=point.access_point_id,
                user_id=None,
                decision="UNKNOWN",
                match_score=None,
                details=f"snapshot | не распознано | UNKNOWN: Лицо не обнаружено/некорректно | сообщение={str(e)}",
            )
            db.add(ev)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()

            flash(f"Распознавание не выполнено: {e}", "danger")
            return redirect(url_for("access_points.monitor", point_id=point.access_point_id))

        match = match_user_by_embedding(db, probe_emb, threshold=0.35, only_active_users=True)
        dec = decide_access_for_user(db, match.user, point)

        subject = match.user.full_name if match.user else "UNKNOWN"
        who_tag = "распознано" if match.user else "не распознано"
        sim_part = f"sim={match.similarity:.3f}" if match.user else "sim=—"
        details = f"snapshot | {who_tag} | {dec.decision}: Проверка по кадру | {sim_part}"

        ev = AccessEvent(
            access_point_id=point.access_point_id,
            user_id=match.user.user_id if match.user else None,
            decision=dec.decision,
            match_score=match.similarity if match.user else None,
            details=details,
        )
        db.add(ev)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Не удалось записать событие доступа (IntegrityError).", "danger")
            return redirect(url_for("access_points.monitor", point_id=point.access_point_id))

        flash(
            f"Проверка кадра: {subject} | {dec.decision} | {sim_part}",
            "success" if dec.decision == "ALLOW" else ("danger" if dec.decision == "DENY" else "secondary"),
        )

        return redirect(url_for("access_points.monitor", point_id=point.access_point_id))
    finally:
        db.close()