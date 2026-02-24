from __future__ import annotations

from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from app.db.session import SessionLocal
from app.db.models import AccessPoint, AccessEvent

from app.core.recognition import (
    decode_image_bytes,
    compute_embedding_from_bgr,
    match_user_by_embedding,
)
from app.core.decision import decide_access_for_user


debug_bp = Blueprint("debug", __name__, url_prefix="/debug")


@debug_bp.route("/recognize", methods=["GET", "POST"])
@login_required
def recognize():
    db = SessionLocal()
    try:
        access_points = db.query(AccessPoint).order_by(AccessPoint.name).all()

        # Defaults for UI
        selected_ap_id = request.values.get("access_point_id", "")
        threshold_str = request.values.get("threshold", "0.35")

        result = None
        decision = None
        saved_event_id = None
        errors = []

        if request.method == "POST":
            # Validate access point
            if not selected_ap_id.isdigit():
                errors.append("Выберите точку доступа.")
            else:
                ap = db.get(AccessPoint, int(selected_ap_id))
                if not ap:
                    errors.append("Точка доступа не найдена.")

            # Threshold
            try:
                threshold = float(threshold_str)
            except ValueError:
                threshold = 0.35

            # File
            f = request.files.get("photo")
            if not f or not f.filename:
                errors.append("Выберите файл изображения.")

            if errors:
                flash("Исправьте ошибки формы.", "danger")
            else:
                file_bytes = f.read()
                try:
                    img_bgr = decode_image_bytes(file_bytes)
                except ValueError as e:
                    flash(str(e), "danger")
                    return render_template(
                        "debug_recognize.html",
                        access_points=access_points,
                        selected_ap_id=selected_ap_id,
                        threshold=threshold_str,
                        result=None,
                        decision=None,
                        saved_event_id=None,
                        errors=["Не удалось прочитать изображение."],
                        active_nav="debug",
                        page_title="Debug распознавания",
                        page_subtitle="Загрузка фото - распознавание - RBAC - запись события",
                    )

                # embedding from image
                try:
                    probe_emb = compute_embedding_from_bgr(img_bgr)
                except ValueError as e:
                    flash(str(e), "danger")
                    return render_template(
                        "debug_recognize.html",
                        access_points=access_points,
                        selected_ap_id=selected_ap_id,
                        threshold=threshold_str,
                        result=None,
                        decision=None,
                        saved_event_id=None,
                        errors=[str(e)],
                        active_nav="debug",
                        page_title="Debug распознавания",
                        page_subtitle="Загрузка фото - распознавание - RBAC - запись события",
                    )

                # match against templates in DB
                result = match_user_by_embedding(db, probe_emb, threshold=threshold, only_active_users=True)

                # RBAC decision
                decision = decide_access_for_user(db, result.user, ap)

                # Save AccessEvent
                details = f"debug_recognize; templates_compared={result.compared_templates}"
                if result.template_id is not None:
                    details += f"; matched_template_id={result.template_id}"

                ev = AccessEvent(
                    access_point_id=ap.access_point_id,
                    user_id=result.user.user_id if result.user else None,
                    decision=decision.decision,
                    match_score=result.similarity if result.user else None,
                    details=details,
                )
                db.add(ev)
                db.commit()
                saved_event_id = ev.event_id

                flash("Готово: распознавание выполнено, событие записано.", "success")

        return render_template(
            "debug_recognize.html",
            access_points=access_points,
            selected_ap_id=selected_ap_id,
            threshold=threshold_str,
            result=result,
            decision=decision,
            saved_event_id=saved_event_id,
            errors=errors,
            active_nav="debug",
            page_title="Debug распознавания",
            page_subtitle="Загрузка фото - распознавание - RBAC - запись события",
        )
    finally:
        db.close()