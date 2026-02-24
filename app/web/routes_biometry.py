from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Dict, Any

import numpy as np
import cv2

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from werkzeug.utils import secure_filename

from app.db.session import SessionLocal
from app.db.models import User, FaceTemplate

from insightface.app import FaceAnalysis


biometry_bp = Blueprint("biometry", __name__)

ALLOWED_EXT = {".jpg", ".jpeg", ".png"}

# --------- Quality thresholds ----------
QUALITY = {
    # детектор
    "min_det_score": 0.50,          # ниже — детект сомнительный
    # размер лица
    "min_face_px": 120,             # минимальная сторона bbox в пикселях (для "эталона")
    "min_face_area_ratio": 0.02,    # минимальная площадь bbox относительно площади кадра (примерно 4%)
    # размытость
    "min_lap_var": 60.0,           # variance of Laplacian (ниже — размыто)
    # яркость / контраст
    "min_brightness": 40.0,         # средняя яркость (0..255)
    "max_brightness": 215.0,
    "min_contrast": 25.0,           # std dev (0..255)
}

_face_app: FaceAnalysis | None = None


def _get_face_app() -> FaceAnalysis:
    """
    Ленивая инициализация InsightFace, чтобы не грузить модель на каждый запрос.
    """
    global _face_app
    if _face_app is not None:
        return _face_app

    app = FaceAnalysis(name="buffalo_l")
    # ctx_id: 0 (GPU) или -1 (CPU)
    try:
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception:
        app.prepare(ctx_id=-1, det_size=(640, 640))

    _face_app = app
    return _face_app


def _uploads_dir() -> Path:
    # uploads рядом с проектом
    base = Path(current_app.root_path).parent
    d = base / "uploads" / "faces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _imdecode(file_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
    return img


def _blur_lap_var(gray: np.ndarray) -> float:
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _brightness_contrast(gray: np.ndarray) -> Tuple[float, float]:
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    return mean, std


def _evaluate_quality(img_bgr: np.ndarray, faces: list) -> Tuple[bool, List[str], List[str], Dict[str, Any], Any]:
    """
    Строгий quality gate:
    - должно быть ровно 1 лицо
    - det_score >= min_det_score
    - лицо достаточно большое
    - не размыто
    - яркость и контраст в норме

    Возвращает:
    ok, reasons, recommendations, metrics, chosen_face
    """
    reasons: List[str] = []
    recs: List[str] = []
    metrics: Dict[str, Any] = {}

    h, w = img_bgr.shape[:2]
    metrics["image_w"] = w
    metrics["image_h"] = h

    if len(faces) == 0:
        reasons.append("Лицо не обнаружено на фото.")
        recs += [
            "Сделайте фото при хорошем освещении (без сильной тени на лице).",
            "Расположите лицо ближе к камере (лицо должно занимать значительную часть кадра).",
            "Убедитесь, что лицо не перекрыто (маска, рука, капюшон, очки с бликами).",
        ]
        return False, reasons, recs, metrics, None

    if len(faces) > 1:
        reasons.append(f"Обнаружено несколько лиц: {len(faces)}. Для регистрации требуется ровно одно лицо.")
        recs += [
            "Оставьте в кадре только одного человека.",
            "Кадрируйте изображение так, чтобы было только одно лицо.",
        ]
        return False, reasons, recs, metrics, None

    face = faces[0]
    # bbox: [x1,y1,x2,y2]
    x1, y1, x2, y2 = face.bbox
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    area_ratio = (bw * bh) / float(w * h)

    det_score = float(getattr(face, "det_score", 0.0))

    metrics.update({
        "det_score": det_score,
        "bbox_w": bw,
        "bbox_h": bh,
        "face_area_ratio": area_ratio,
    })

    # --- детектор ---
    if det_score < QUALITY["min_det_score"]:
        reasons.append(f"Низкая уверенность детектора лица (det_score={det_score:.2f}).")
        recs += [
            "Сделайте фото с более чётким лицом (без сильного размытия).",
            "Избегайте бокового ракурса — лучше фронтально.",
            "Улучшите освещение (лицо должно быть хорошо видно).",
        ]

    # --- размер лица ---
    if min(bw, bh) < QUALITY["min_face_px"]:
        reasons.append(f"Лицо слишком маленькое на фото (bbox={bw}×{bh}px).")
        recs += [
            f"Приблизьте лицо к камере (минимум ~{QUALITY['min_face_px']}px по меньшей стороне).",
            "Не используйте фото, где лицо далеко/мелкое.",
        ]

    if area_ratio < QUALITY["min_face_area_ratio"]:
        reasons.append(f"Лицо занимает слишком малую часть кадра (≈{area_ratio*100:.1f}% площади).")
        recs += [
            "Кадрируйте изображение так, чтобы лицо занимало больше места.",
            "Используйте портретное фото крупным планом.",
        ]

    # --- размытость / освещение ---
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    lap_var = _blur_lap_var(gray)
    bright, contrast = _brightness_contrast(gray)

    metrics.update({
        "lap_var": lap_var,
        "brightness": bright,
        "contrast": contrast,
    })

    if lap_var < QUALITY["min_lap_var"]:
        reasons.append(f"Фото размыто (резкость низкая, LapVar={lap_var:.0f}).")
        recs += [
            "Сделайте фото без движения (не шевелить головой, камера неподвижна).",
            "Используйте более качественную камеру/режим без шума.",
            "Не используйте снимки из мессенджеров с сильным сжатием.",
        ]

    if bright < QUALITY["min_brightness"]:
        reasons.append(f"Фото слишком тёмное (яркость={bright:.0f}).")
        recs += [
            "Добавьте освещение (лампа/окно перед лицом).",
            "Избегайте подсветки сзади (контровой свет).",
        ]

    if bright > QUALITY["max_brightness"]:
        reasons.append(f"Фото слишком светлое/пересвечено (яркость={bright:.0f}).")
        recs += [
            "Уберите прямой свет в лицо или уменьшите экспозицию.",
            "Сфотографируйтесь без бликов/пересветов.",
        ]

    if contrast < QUALITY["min_contrast"]:
        reasons.append(f"Низкий контраст (контраст={contrast:.0f}).")
        recs += [
            "Сделайте фото при более равномерном освещении лица.",
            "Избегайте сильного шума/смазанных изображений.",
        ]

    ok = (len(reasons) == 0)
    # Удалим дубли рекомендаций (чтобы UI не раздувался)
    if recs:
        recs = list(dict.fromkeys(recs))

    return ok, reasons, recs, metrics, face


@biometry_bp.route("/users/<int:user_id>/biometry", methods=["GET", "POST"])
@login_required
def register_face(user_id: int):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash("Пользователь не найден", "danger")
            return redirect(url_for("users.list"))

        reasons: List[str] = []
        recommendations: List[str] = []
        metrics: Dict[str, Any] | None = None
        saved_path: str | None = None
        created_template_id: int | None = None

        if request.method == "POST":
            f = request.files.get("photo")
            if not f or not f.filename:
                flash("Выберите файл изображения", "danger")
                return redirect(url_for("biometry.register_face", user_id=user_id))

            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_EXT:
                flash("Разрешены только JPG/PNG", "danger")
                return redirect(url_for("biometry.register_face", user_id=user_id))

            file_bytes = f.read()
            img = _imdecode(file_bytes)
            if img is None:
                flash("Не удалось прочитать изображение. Проверьте файл.", "danger")
                return redirect(url_for("biometry.register_face", user_id=user_id))

            face_app = _get_face_app()
            faces = face_app.get(img)

            ok, reasons, recommendations, metrics, face = _evaluate_quality(img, faces)

            if not ok:
                # строгий режим: НЕ сохраняем ни шаблон, ни файл (чтобы не копить мусор)
                flash("Отказано: фото не прошло контроль качества.", "danger")
            else:
                # сохраняем файл
                safe = secure_filename(Path(f.filename).stem)
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"user_{user_id}_{ts}_{safe}{ext}"
                out_dir = _uploads_dir()
                out_path = out_dir / filename
                out_path.write_bytes(file_bytes)
                saved_path = str(out_path)

                # embedding -> bytes
                emb = np.asarray(face.embedding, dtype=np.float32)  # (512,)
                emb_bytes = emb.tobytes()

                # source_note можно использовать для аудита/отчёта
                source_note = (
                    f"upload:{filename}; "
                    f"det={metrics.get('det_score'):.2f}; "
                    f"lap={metrics.get('lap_var'):.0f}; "
                    f"b={metrics.get('brightness'):.0f}; "
                    f"c={metrics.get('contrast'):.0f}"
                )

                tpl = FaceTemplate(user_id=user.user_id, embedding=emb_bytes, source_note=source_note)
                db.add(tpl)
                db.commit()
                created_template_id = tpl.template_id

                flash("Шаблон лица успешно создан и сохранён.", "success")

        return render_template(
            "biometry_register.html",
            user=user,
            saved_path=saved_path,
            created_template_id=created_template_id,
            reasons=reasons,
            recommendations=recommendations,
            metrics=metrics,
            active_nav="users",
            page_title="Регистрация лица",
            page_subtitle=f"Пользователь: {user.full_name}",
        )
    finally:
        db.close()


@biometry_bp.route("/users/<int:user_id>/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(user_id: int, template_id: int):
    db = SessionLocal()
    try:
        tpl = db.get(FaceTemplate, template_id)
        if not tpl or tpl.user_id != user_id:
            flash("Шаблон не найден", "danger")
            return redirect(url_for("users.edit", user_id=user_id))

        db.delete(tpl)
        db.commit()
        flash("Шаблон удалён", "success")
        return redirect(url_for("users.edit", user_id=user_id))
    finally:
        db.close()