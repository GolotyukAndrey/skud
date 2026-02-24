from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.models import Role

roles_bp = Blueprint("roles", __name__, url_prefix="/roles")


@roles_bp.route("/")
@login_required
def list():
    db = SessionLocal()
    try:
        roles = db.query(Role).order_by(Role.role_id.desc()).all()
        return render_template("roles_list.html", roles=roles, active_nav="roles")
    finally:
        db.close()


@roles_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip() or None

            if not name:
                flash("Укажите название роли", "danger")
                return render_template("role_form.html", role=None, active_nav="roles")

            # Предпроверка уникальности по имени
            exists = db.query(Role).filter(Role.name == name).first()
            if exists:
                flash("Роль с таким названием уже существует", "danger")
                return render_template("role_form.html", role=None, active_nav="roles")

            role = Role(name=name, description=description)
            db.add(role)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя добавить роль: нарушено ограничение целостности (возможно, дубликат).", "danger")
                return render_template("role_form.html", role=None, active_nav="roles")

            flash("Роль добавлена", "success")
            return redirect(url_for("roles.list"))

        return render_template("role_form.html", role=None, active_nav="roles")
    finally:
        db.close()


@roles_bp.route("/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def edit(role_id: int):
    db = SessionLocal()
    try:
        role = db.get(Role, role_id)
        if not role:
            flash("Роль не найдена", "danger")
            return redirect(url_for("roles.list"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip() or None

            if not name:
                flash("Укажите название роли", "danger")
                return render_template("role_form.html", role=role, active_nav="roles")

            # Если переименовываем — проверим, что нет другой роли с таким именем
            exists = db.query(Role).filter(Role.name == name, Role.role_id != role.role_id).first()
            if exists:
                flash("Роль с таким названием уже существует", "danger")
                return render_template("role_form.html", role=role, active_nav="roles")

            role.name = name
            role.description = description

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Нельзя сохранить роль: нарушено ограничение целостности.", "danger")
                return render_template("role_form.html", role=role, active_nav="roles")

            flash("Изменения сохранены", "success")
            return redirect(url_for("roles.list"))

        return render_template("role_form.html", role=role, active_nav="roles")
    finally:
        db.close()


@roles_bp.route("/<int:role_id>/delete", methods=["POST"])
@login_required
def delete(role_id: int):
    db = SessionLocal()
    try:
        role = db.get(Role, role_id)
        if not role:
            flash("Роль не найдена", "danger")
            return redirect(url_for("roles.list"))

        db.delete(role)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Нельзя удалить роль: она используется (назначена пользователям или участвует в правилах доступа).", "danger")
            return redirect(url_for("roles.list"))

        flash("Роль удалена", "success")
        return redirect(url_for("roles.list"))
    finally:
        db.close()