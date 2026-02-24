from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import desc, func

from app.db.session import SessionLocal
from app.db.models import User, FaceTemplate, Role

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.route("/")
@login_required
def list():
    q = request.args.get("q", "").strip()

    db = SessionLocal()
    try:
        query = db.query(User)

        if q:
            query = query.filter(User.full_name.ilike(f"%{q}%"))

        users = query.order_by(desc(User.user_id)).limit(500).all()

        # количество шаблонов лица на пользователя
        user_ids = [u.user_id for u in users]
        tpl_counts = {}
        if user_ids:
            rows = (
                db.query(FaceTemplate.user_id, func.count(FaceTemplate.template_id))
                .filter(FaceTemplate.user_id.in_(user_ids))
                .group_by(FaceTemplate.user_id)
                .all()
            )
            tpl_counts = {uid: cnt for uid, cnt in rows}

        return render_template(
            "users_list.html",
            users=users,
            tpl_counts=tpl_counts,
            q=q,
            active_nav="users",
            page_title="Пользователи",
            page_subtitle="Справочник пользователей СКУД. Биометрия добавляется отдельным шагом.",
        )
    finally:
        db.close()


@users_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        all_roles = db.query(Role).order_by(Role.name).all()

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip() or None
            phone = request.form.get("phone", "").strip() or None
            is_active = request.form.get("is_active") == "on"

            # роли из формы (на этапе создания тоже принимаем)
            selected_role_ids = request.form.getlist("role_ids")
            try:
                selected_role_ids = {int(x) for x in selected_role_ids}
            except ValueError:
                selected_role_ids = set()

            # если валидация упала — надо вернуть галочки назад
            assigned_role_ids = selected_role_ids.copy()

            if not full_name:
                flash("Укажите ФИО пользователя", "danger")
                return render_template(
                    "user_form.html",
                    user=None,
                    templates=[],
                    all_roles=all_roles,
                    assigned_role_ids=assigned_role_ids,
                    active_nav="users",
                    page_title="Новый пользователь",
                    page_subtitle="Создание пользователя + назначение ролей",
                )

            # 1) создаём пользователя
            u = User(full_name=full_name, email=email, phone=phone, is_active=is_active)
            db.add(u)
            db.commit()   # получаем u.user_id
            db.refresh(u)

            # 2) назначаем роли (после того как есть user_id)
            if selected_role_ids:
                selected_roles = db.query(Role).filter(Role.role_id.in_(selected_role_ids)).all()
            else:
                selected_roles = []

            u.roles = selected_roles
            db.commit()

            flash("Пользователь создан, роли назначены", "success")
            return redirect(url_for("users.edit", user_id=u.user_id))

        # GET: новый пользователь
        return render_template(
            "user_form.html",
            user=None,
            templates=[],
            all_roles=all_roles,
            assigned_role_ids=set(),
            active_nav="users",
            page_title="Новый пользователь",
            page_subtitle="Создание пользователя + назначение ролей",
        )
    finally:
        db.close()


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit(user_id: int):
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Пользователь не найден", "danger")
            return redirect(url_for("users.list"))

        # Все роли для чекбоксов
        all_roles = db.query(Role).order_by(Role.name).all()
        assigned_role_ids = {r.role_id for r in u.roles}

        if request.method == "POST":
            u.full_name = request.form.get("full_name", "").strip()
            u.email = request.form.get("email", "").strip() or None
            u.phone = request.form.get("phone", "").strip() or None
            u.is_active = request.form.get("is_active") == "on"

            selected_role_ids = request.form.getlist("role_ids")
            try:
                selected_role_ids = {int(x) for x in selected_role_ids}
            except ValueError:
                selected_role_ids = set()

            # Валидация
            if not u.full_name:
                flash("Укажите ФИО пользователя", "danger")
            else:
                selected_roles = []
                if selected_role_ids:
                    selected_roles = db.query(Role).filter(Role.role_id.in_(selected_role_ids)).all()
                u.roles = selected_roles

                db.commit()
                flash("Изменения сохранены", "success")
                return redirect(url_for("users.edit", user_id=u.user_id))

            assigned_role_ids = {r.role_id for r in u.roles}

        templates = (
            db.query(FaceTemplate)
            .filter(FaceTemplate.user_id == u.user_id)
            .order_by(desc(FaceTemplate.created_at))
            .all()
        )

        return render_template(
            "user_form.html",
            user=u,
            templates=templates,
            all_roles=all_roles,
            assigned_role_ids=assigned_role_ids,
            active_nav="users",
            page_title="Редактирование пользователя",
            page_subtitle="Данные + роли + биометрия",
        )
    finally:
        db.close()


@users_bp.route("/<int:user_id>/delete", methods=["POST"])
@login_required
def delete(user_id: int):
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if u:
            db.delete(u)
            db.commit()
            flash("Пользователь удалён", "success")
        else:
            flash("Пользователь не найден", "danger")
        return redirect(url_for("users.list"))
    finally:
        db.close()