from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash

from app.db.session import SessionLocal
from app.db.models import Admin

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        db = SessionLocal()
        try:
            admin = db.query(Admin).filter_by(username=username).first()
        finally:
            db.close()

        if admin and check_password_hash(admin.password_hash, password):
            login_user(admin)
            return redirect(url_for("dashboard.index"))
        else:
            flash("Неверный логин или пароль", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))