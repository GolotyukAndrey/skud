from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.models import Camera

cameras_bp = Blueprint("cameras", __name__, url_prefix="/cameras")

SOURCE_TYPES = [("webcam", "Webcam"), ("rtsp", "RTSP"), ("file", "Video file")]


@cameras_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        cameras = db.query(Camera).order_by(Camera.camera_id.desc()).all()
        return render_template("cameras_list.html", cameras=cameras, active_nav="cameras")
    finally:
        db.close()


@cameras_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            source_type = request.form.get("source_type", "").strip()
            source = request.form.get("source", "").strip()
            is_active = (request.form.get("is_active") == "on")

            if not name or source_type not in dict(SOURCE_TYPES) or not source:
                flash("Заполните все поля корректно", "danger")
                return render_template("camera_form.html", camera=None, source_types=SOURCE_TYPES, active_nav="cameras")

            # Предпроверка дубля по имени (если у тебя name уникален)
            exists = db.query(Camera).filter(Camera.name == name).first()
            if exists:
                flash("Камера с таким названием уже существует", "danger")
                return render_template("camera_form.html", camera=None, source_types=SOURCE_TYPES, active_nav="cameras")

            cam = Camera(name=name, source_type=source_type, source=source, is_active=is_active)
            db.add(cam)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя добавить камеру: нарушено ограничение целостности (возможно, дубликат).", "danger")
                return render_template("camera_form.html", camera=None, source_types=SOURCE_TYPES, active_nav="cameras")

            flash("Камера добавлена", "success")
            return redirect(url_for("cameras.list"))

        return render_template("camera_form.html", camera=None, source_types=SOURCE_TYPES, active_nav="cameras")
    finally:
        db.close()


@cameras_bp.route("/<int:camera_id>/edit", methods=["GET", "POST"])
@login_required
def edit(camera_id: int):
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if not cam:
            flash("Камера не найдена", "danger")
            return redirect(url_for("cameras.list"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            source_type = request.form.get("source_type", "").strip()
            source = request.form.get("source", "").strip()
            is_active = (request.form.get("is_active") == "on")

            if not name or source_type not in dict(SOURCE_TYPES) or not source:
                flash("Заполните все поля корректно", "danger")
                return render_template("camera_form.html", camera=cam, source_types=SOURCE_TYPES, active_nav="cameras")

            # Проверка дубля имени при переименовании
            exists = db.query(Camera).filter(Camera.name == name, Camera.camera_id != cam.camera_id).first()
            if exists:
                flash("Камера с таким названием уже существует", "danger")
                return render_template("camera_form.html", camera=cam, source_types=SOURCE_TYPES, active_nav="cameras")

            cam.name = name
            cam.source_type = source_type
            cam.source = source
            cam.is_active = is_active

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя сохранить камеру: нарушено ограничение целостности.", "danger")
                return render_template("camera_form.html", camera=cam, source_types=SOURCE_TYPES, active_nav="cameras")

            flash("Изменения сохранены", "success")
            return redirect(url_for("cameras.list"))

        return render_template("camera_form.html", camera=cam, source_types=SOURCE_TYPES, active_nav="cameras")
    finally:
        db.close()


@cameras_bp.route("/<int:camera_id>/delete", methods=["POST"])
@login_required
def delete(camera_id: int):
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if not cam:
            flash("Камера не найдена", "danger")
            return redirect(url_for("cameras.list"))

        db.delete(cam)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Нельзя удалить камеру: она используется (привязана к точке доступа). Лучше отключите её.", "danger")
            return redirect(url_for("cameras.list"))

        flash("Камера удалена", "success")
        return redirect(url_for("cameras.list"))
    finally:
        db.close()