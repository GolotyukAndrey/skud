from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.models import Zone

zones_bp = Blueprint("zones", __name__, url_prefix="/zones")


@zones_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        zones = db.query(Zone).order_by(Zone.zone_id.desc()).all()
        return render_template("zones_list.html", zones=zones, active_nav="zones")
    finally:
        db.close()


@zones_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip() or None

            if not name:
                flash("Укажите название зоны", "danger")
                return render_template("zone_form.html", zone=None, active_nav="zones")

            exists = db.query(Zone).filter(Zone.name == name).first()
            if exists:
                flash("Зона с таким названием уже существует", "danger")
                return render_template("zone_form.html", zone=None, active_nav="zones")

            zone = Zone(name=name, description=description)
            db.add(zone)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя добавить зону: нарушено ограничение целостности (возможно, дубликат).", "danger")
                return render_template("zone_form.html", zone=None, active_nav="zones")

            flash("Зона добавлена", "success")
            return redirect(url_for("zones.list"))

        return render_template("zone_form.html", zone=None, active_nav="zones")
    finally:
        db.close()


@zones_bp.route("/<int:zone_id>/edit", methods=["GET", "POST"])
@login_required
def edit(zone_id: int):
    db = SessionLocal()
    try:
        zone = db.get(Zone, zone_id)
        if not zone:
            flash("Зона не найдена", "danger")
            return redirect(url_for("zones.list"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip() or None

            if not name:
                flash("Укажите название зоны", "danger")
                return render_template("zone_form.html", zone=zone, active_nav="zones")

            exists = db.query(Zone).filter(Zone.name == name, Zone.zone_id != zone.zone_id).first()
            if exists:
                flash("Зона с таким названием уже существует", "danger")
                return render_template("zone_form.html", zone=zone, active_nav="zones")

            zone.name = name
            zone.description = description

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя сохранить зону: нарушено ограничение целостности.", "danger")
                return render_template("zone_form.html", zone=zone, active_nav="zones")

            flash("Изменения сохранены", "success")
            return redirect(url_for("zones.list"))

        return render_template("zone_form.html", zone=zone, active_nav="zones")
    finally:
        db.close()


@zones_bp.route("/<int:zone_id>/delete", methods=["POST"])
@login_required
def delete(zone_id: int):
    db = SessionLocal()
    try:
        zone = db.get(Zone, zone_id)
        if not zone:
            flash("Зона не найдена", "danger")
            return redirect(url_for("zones.list"))

        db.delete(zone)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Нельзя удалить зону: она используется (точки доступа/правила доступа).", "danger")
            return redirect(url_for("zones.list"))

        flash("Зона удалена", "success")
        return redirect(url_for("zones.list"))
    finally:
        db.close()