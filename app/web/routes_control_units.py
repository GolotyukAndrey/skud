from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.db.session import SessionLocal
from app.db.models import ControlUnit

control_units_bp = Blueprint("control_units", __name__, url_prefix="/control-units")

UNIT_TYPES = [("stub", "Stub (эмуляция)"), ("http", "HTTP endpoint")]


@control_units_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        units = db.query(ControlUnit).order_by(ControlUnit.control_unit_id.desc()).all()
        return render_template("control_units_list.html", units=units, unit_types=dict(UNIT_TYPES), active_nav="control_units")
    finally:
        db.close()


@control_units_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        unit_type = request.form.get("unit_type", "stub").strip()
        endpoint = request.form.get("endpoint", "").strip() or None
        is_active = request.form.get("is_active") == "on"

        if not name or unit_type not in dict(UNIT_TYPES):
            flash("Заполните поля корректно", "danger")
            return render_template("control_unit_form.html", unit=None, unit_types=UNIT_TYPES, active_nav="control_units")

        db = SessionLocal()
        try:
            unit = ControlUnit(name=name, unit_type=unit_type, endpoint=endpoint, is_active=is_active)
            db.add(unit)
            db.commit()
            flash("Исполнительное устройство добавлено", "success")
            return redirect(url_for("control_units.list"))
        finally:
            db.close()

    return render_template("control_unit_form.html", unit=None, unit_types=UNIT_TYPES, active_nav="control_units")


@control_units_bp.route("/<int:unit_id>/edit", methods=["GET", "POST"])
@login_required
def edit(unit_id: int):
    db = SessionLocal()
    try:
        unit = db.get(ControlUnit, unit_id)
        if not unit:
            flash("Устройство не найдено", "danger")
            return redirect(url_for("control_units.list"))

        if request.method == "POST":
            unit.name = request.form.get("name", "").strip()
            unit.unit_type = request.form.get("unit_type", "stub").strip()
            unit.endpoint = request.form.get("endpoint", "").strip() or None
            unit.is_active = request.form.get("is_active") == "on"

            if not unit.name or unit.unit_type not in dict(UNIT_TYPES):
                flash("Заполните поля корректно", "danger")
                return render_template("control_unit_form.html", unit=unit, unit_types=UNIT_TYPES, active_nav="control_units")

            db.commit()
            flash("Изменения сохранены", "success")
            return redirect(url_for("control_units.list"))

        return render_template("control_unit_form.html", unit=unit, unit_types=UNIT_TYPES, active_nav="control_units")
    finally:
        db.close()


@control_units_bp.route("/<int:unit_id>/delete", methods=["POST"])
@login_required
def delete(unit_id: int):
    db = SessionLocal()
    try:
        unit = db.get(ControlUnit, unit_id)
        if unit:
            db.delete(unit)
            db.commit()
            flash("Устройство удалено", "success")
        else:
            flash("Устройство не найдено", "danger")
        return redirect(url_for("control_units.list"))
    finally:
        db.close()


# MVP-тест команд
@control_units_bp.route("/<int:unit_id>/test/<cmd>", methods=["POST"])
@login_required
def test_cmd(unit_id: int, cmd: str):
    if cmd not in ("open", "deny"):
        flash("Неизвестная команда", "danger")
        return redirect(url_for("control_units.list"))

    db = SessionLocal()
    try:
        unit = db.get(ControlUnit, unit_id)
        if not unit:
            flash("Устройство не найдено", "danger")
            return redirect(url_for("control_units.list"))

        flash(f"Тестовая команда отправлена: {cmd.upper()} (unit={unit.name})", "success")
        return redirect(url_for("control_units.list"))
    finally:
        db.close()