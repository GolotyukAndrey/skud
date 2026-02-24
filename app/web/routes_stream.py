import time
from flask import Blueprint, Response
from flask_login import login_required

from app.db.session import SessionLocal
from app.db.models import AccessPoint

from app.runtime.camera_manager import camera_manager

stream_bp = Blueprint("stream", __name__, url_prefix="/stream")


def _mjpeg_generator(access_point_id: int):
    db = SessionLocal()
    try:
        ap = db.get(AccessPoint, access_point_id)
        if not ap or not ap.camera:
            return

        # запускаем воркер на эту точку доступа
        camera_manager.ensure_started(
            key=access_point_id,
            source_type=ap.camera.source_type,
            source=ap.camera.source,
        )

        while True:
            st = camera_manager.get_state(access_point_id)
            if st is None:
                time.sleep(0.2)
                continue

            if st.last_jpeg:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + st.last_jpeg + b"\r\n")
            else:
                # пока нет кадра — подождём
                time.sleep(0.1)

    finally:
        db.close()


@stream_bp.route("/access-point/<int:access_point_id>.mjpg")
@login_required
def access_point_mjpeg(access_point_id: int):
    gen = _mjpeg_generator(access_point_id)
    return Response(gen, mimetype="multipart/x-mixed-replace; boundary=frame")