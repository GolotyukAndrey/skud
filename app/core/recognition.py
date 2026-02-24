from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
import cv2
from PIL import Image, ImageOps
import io

from sqlalchemy.orm import Session
from insightface.app import FaceAnalysis

from app.db.models import FaceTemplate, User


_face_app: FaceAnalysis | None = None


def get_face_app() -> FaceAnalysis:
    global _face_app
    if _face_app is not None:
        return _face_app

    app = FaceAnalysis(name="buffalo_l")
    try:
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception:
        app.prepare(ctx_id=-1, det_size=(640, 640))

    _face_app = app
    return _face_app


# ---------------- Image utils ----------------
def decode_image_bytes(file_bytes: bytes) -> np.ndarray:
    """
    Decode image bytes -> BGR ndarray (OpenCV).
    Handles EXIF orientation (phone photos).
    Raises ValueError on failure.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        arr = np.array(img)  # RGB
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return bgr
    except Exception as e:
        raise ValueError(f"Cannot decode image: {e}")


def compute_embedding_from_bgr(img_bgr: np.ndarray) -> np.ndarray:
    """
    Returns embedding float32 shape (512,).
    Raises ValueError with a user-friendly message.
    """
    app = get_face_app()
    faces = app.get(img_bgr)

    if len(faces) == 0:
        raise ValueError("Лицо не обнаружено на изображении.")
    if len(faces) > 1:
        raise ValueError(f"Обнаружено несколько лиц ({len(faces)}). Нужно ровно одно лицо.")

    face = faces[0]
    emb = np.asarray(face.embedding, dtype=np.float32)
    if emb.ndim != 1:
        emb = emb.reshape(-1).astype(np.float32)
    return emb


def bytes_to_embedding(embedding_bytes: bytes) -> np.ndarray:
    """
    FaceTemplate.embedding is LargeBinary containing float32[512] bytes.
    """
    arr = np.frombuffer(embedding_bytes, dtype=np.float32)
    return arr


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity in [-1..1], higher is more similar.
    """
    a = a.astype(np.float32, copy=False)
    b = b.astype(np.float32, copy=False)

    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return -1.0
    return float(np.dot(a, b) / (na * nb))


@dataclass
class MatchResult:
    user: Optional[User]
    template_id: Optional[int]
    similarity: float
    # debug info
    compared_templates: int


def match_user_by_embedding(
    db: Session,
    probe_embedding: np.ndarray,
    threshold: float = 0.35,
    only_active_users: bool = True,
) -> MatchResult:
    """
    Compares probe embedding to all stored templates and returns best match.

    threshold: minimal cosine similarity to accept match.
    """
    templates: List[FaceTemplate] = db.query(FaceTemplate).all()

    best_sim = -1.0
    best_tpl: FaceTemplate | None = None

    for tpl in templates:
        if only_active_users and tpl.user and (tpl.user.is_active is False):
            continue

        ref = bytes_to_embedding(tpl.embedding)
        if ref.shape[0] != probe_embedding.shape[0]:
            continue

        sim = cosine_similarity(probe_embedding, ref)
        if sim > best_sim:
            best_sim = sim
            best_tpl = tpl

    compared = len(templates)

    if best_tpl is None or best_sim < threshold:
        return MatchResult(
            user=None,
            template_id=None,
            similarity=best_sim if best_sim != -1.0 else 0.0,
            compared_templates=compared,
        )

    return MatchResult(
        user=best_tpl.user,
        template_id=best_tpl.template_id,
        similarity=best_sim,
        compared_templates=compared,
    )