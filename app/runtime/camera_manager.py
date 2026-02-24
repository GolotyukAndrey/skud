from __future__ import annotations

import cv2
import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Tuple


@dataclass
class CameraState:
    last_frame_bgr: Optional[object] = None  # numpy.ndarray
    last_jpeg: Optional[bytes] = None
    last_ts: float = 0.0
    is_running: bool = False
    error: Optional[str] = None


class CameraWorker:
    def __init__(self, source_type: str, source: str):
        self.source_type = source_type
        self.source = source
        self.state = CameraState()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._release()

    def _release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None

    def _open(self):
        if self.source_type == "webcam":
            try:
                idx = int(self.source)
            except ValueError:
                idx = 0
            self._cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # Windows friendly
        else:
            self._cap = cv2.VideoCapture(self.source)

    def _run(self):
        with self._lock:
            self.state.is_running = True
            self.state.error = None

        try:
            self._open()
            if self._cap is None or not self._cap.isOpened():
                with self._lock:
                    self.state.error = "Не удалось открыть источник камеры."
                return

            # Чтобы CPU не улетал, ограничение частоты кадров
            target_fps = 10
            sleep_s = 1.0 / target_fps

            # Прогрев
            for _ in range(5):
                ok, _ = self._cap.read()
                time.sleep(0.03)

            while not self._stop.is_set():
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    time.sleep(0.2)
                    continue

                ok2, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok2:
                    time.sleep(sleep_s)
                    continue

                now = time.time()
                with self._lock:
                    self.state.last_frame_bgr = frame
                    self.state.last_jpeg = jpg.tobytes()
                    self.state.last_ts = now
                    self.state.error = None

                time.sleep(sleep_s)

        except Exception as e:
            with self._lock:
                self.state.error = str(e)
        finally:
            self._release()
            with self._lock:
                self.state.is_running = False


class CameraManager:
    """
    Хранит воркеры по ключу (access_point_id).
    """
    def __init__(self):
        self._workers: Dict[int, CameraWorker] = {}
        self._lock = threading.Lock()

    def ensure_started(self, key: int, source_type: str, source: str) -> CameraWorker:
        with self._lock:
            w = self._workers.get(key)
            if w is None:
                w = CameraWorker(source_type, source)
                self._workers[key] = w
                w.start()
            else:
                # если источник изменился — можно перезапустить (опционально)
                if w.source_type != source_type or w.source != source:
                    w.stop()
                    w = CameraWorker(source_type, source)
                    self._workers[key] = w
                    w.start()
                else:
                    w.start()
            return w

    def get_state(self, key: int) -> Optional[CameraState]:
        with self._lock:
            w = self._workers.get(key)
            if not w:
                return None
            with w._lock:
                return CameraState(
                    last_frame_bgr=w.state.last_frame_bgr,
                    last_jpeg=w.state.last_jpeg,
                    last_ts=w.state.last_ts,
                    is_running=w.state.is_running,
                    error=w.state.error,
                )

    def get_latest_frame(self, key: int):
        with self._lock:
            w = self._workers.get(key)
            if not w:
                return None
            with w._lock:
                return w.state.last_frame_bgr

    def stop(self, key: int):
        with self._lock:
            w = self._workers.pop(key, None)
        if w:
            w.stop()


# Глобальный singleton (для Flask процесса)
camera_manager = CameraManager()