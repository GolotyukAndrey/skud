from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.models import RoleZonePermission, Role, Zone

permissions_bp = Blueprint("permissions", __name__, url_prefix="/permissions")


@permissions_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        rules = (
            db.query(RoleZonePermission)
            .join(Role)
            .join(Zone)
            .order_by(Role.name, Zone.name)
            .all()
        )
        return render_template("permissions_list.html", rules=rules, active_nav="permissions")
    finally:
        db.close()


@permissions_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        roles = db.query(Role).order_by(Role.name).all()
        zones = db.query(Zone).order_by(Zone.name).all()

        if request.method == "POST":
            role_id_raw = (request.form.get("role_id") or "").strip()
            zone_id_raw = (request.form.get("zone_id") or "").strip()
            is_allowed_raw = (request.form.get("is_allowed") or "").strip().lower()

            if not role_id_raw.isdigit() or not zone_id_raw.isdigit():
                flash("Выберите роль и зону", "danger")
                return render_template(
                    "permission_form.html",
                    roles=roles,
                    zones=zones,
                    active_nav="permissions",
                )

            role_id = int(role_id_raw)
            zone_id = int(zone_id_raw)
            is_allowed = (is_allowed_raw == "true")

            # Проверим, что role и zone существуют
            if not db.get(Role, role_id):
                flash("Выбранная роль не найдена", "danger")
                return render_template("permission_form.html", roles=roles, zones=zones, active_nav="permissions")
            if not db.get(Zone, zone_id):
                flash("Выбранная зона не найдена", "danger")
                return render_template("permission_form.html", roles=roles, zones=zones, active_nav="permissions")

            # UPSERT: если правило уже есть — обновим is_allowed
            rule = (
                db.query(RoleZonePermission)
                .filter(RoleZonePermission.role_id == role_id, RoleZonePermission.zone_id == zone_id)
                .one_or_none()
            )

            if rule is None:
                rule = RoleZonePermission(role_id=role_id, zone_id=zone_id, is_allowed=is_allowed)
                db.add(rule)
                action_msg = "Правило доступа добавлено"
            else:
                rule.is_allowed = is_allowed
                action_msg = "Правило доступа обновлено"

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя сохранить правило: нарушено ограничение целостности (возможно, дубликат).", "danger")
                return render_template(
                    "permission_form.html",
                    roles=roles,
                    zones=zones,
                    active_nav="permissions",
                )

            flash(action_msg, "success")
            return redirect(url_for("permissions.list"))

        return render_template(
            "permission_form.html",
            roles=roles,
            zones=zones,
            active_nav="permissions"
        )
    finally:
        db.close()


@permissions_bp.route("/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete(rule_id: int):
    db = SessionLocal()
    try:
        rule = db.get(RoleZonePermission, rule_id)
        if not rule:
            flash("Правило не найдено", "danger")
            return redirect(url_for("permissions.list"))

        db.delete(rule)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Нельзя удалить правило: есть связанные данные или ограничение целостности.", "danger")
            return redirect(url_for("permissions.list"))

        flash("Правило удалено", "success")
        return redirect(url_for("permissions.list"))
    finally:
        db.close()