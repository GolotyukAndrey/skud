from __future__ import annotations

import time
import threading
import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor
from app.db.session import SessionLocal
from app.db.models import AccessPoint, AccessEvent, FaceTemplate, User, RoleZonePermission
from app.runtime.camera_manager import camera_manager
from app.core.recognition import get_face_app, bytes_to_embedding


# Настройки
ANALYSIS_INTERVAL_SEC = 0.7         # как часто анализировать кадр по точке (≈1–2 раза/сек)
COOLDOWN_AFTER_EVENT_SEC = 2.5      # антиспам событий на точку
COOLDOWN_AFTER_ALLOW_SEC = 6.0      # после ALLOW — дольше, чтобы не открывать 10 раз
MATCH_THRESHOLD = 0.5              # порог cosine similarity
TEMPLATE_CACHE_TTL_SEC = 60.0       # обновлять кэш шаблонов раз в минуту
MAX_WORKERS = 2                     # пул задач (2 обычно норм для CPU)


@dataclass
class APStatus:
    ap_id: int
    running: bool
    last_check_ts: float = 0.0
    last_event_ts: float = 0.0
    last_decision: str = ""
    last_subject: str = ""
    last_similarity: float = 0.0
    last_error: str = ""
    next_allowed_ts: float = 0.0
    in_flight: bool = False


class TemplateIndex:
    """
    Кэш шаблонов:
      - embeddings_norm: (N,512) float32 нормированные
      - template_ids: (N,)
      - user_ids: (N,)
    """
    def __init__(self):
        self.embeddings_norm: Optional[np.ndarray] = None
        self.template_ids: Optional[np.ndarray] = None
        self.user_ids: Optional[np.ndarray] = None
        self.updated_ts: float = 0.0
        self.count: int = 0

    def needs_refresh(self) -> bool:
        return (time.time() - self.updated_ts) > TEMPLATE_CACHE_TTL_SEC or self.embeddings_norm is None

    def refresh(self):
        db = SessionLocal()
        try:
            tpls: List[FaceTemplate] = db.query(FaceTemplate).all()
            embs = []
            tpl_ids = []
            usr_ids = []
            for t in tpls:
                arr = bytes_to_embedding(t.embedding)
                if arr.shape[0] != 512:
                    continue
                norm = np.linalg.norm(arr)
                if norm == 0:
                    continue
                embs.append((arr / norm).astype(np.float32))
                tpl_ids.append(t.template_id)
                usr_ids.append(t.user_id)

            if embs:
                self.embeddings_norm = np.stack(embs, axis=0)
                self.template_ids = np.asarray(tpl_ids, dtype=np.int32)
                self.user_ids = np.asarray(usr_ids, dtype=np.int32)
                self.count = int(self.embeddings_norm.shape[0])
            else:
                self.embeddings_norm = None
                self.template_ids = None
                self.user_ids = None
                self.count = 0

            self.updated_ts = time.time()
        finally:
            db.close()

    def match(self, probe_embedding: np.ndarray) -> Tuple[Optional[int], Optional[int], float]:
        """
        Возвращает (user_id, template_id, similarity) или (None,None,best_sim)
        """
        if self.embeddings_norm is None or self.count == 0:
            return None, None, 0.0

        probe = probe_embedding.astype(np.float32, copy=False)
        n = np.linalg.norm(probe)
        if n == 0:
            return None, None, 0.0
        probe = probe / n

        sims = self.embeddings_norm @ probe
        idx = int(np.argmax(sims))
        best_sim = float(sims[idx])
        if best_sim < MATCH_THRESHOLD:
            return None, None, best_sim
        return int(self.user_ids[idx]), int(self.template_ids[idx]), best_sim


class AccessWorkerManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._status: Dict[int, APStatus] = {}
        self._running_flags: Dict[int, bool] = {}
        self._stop_evt = threading.Event()

        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)

        self._index = TemplateIndex()

        self._thread.start()


    def start(self, ap_id: int):
        with self._lock:
            self._running_flags[ap_id] = True
            st = self._status.get(ap_id)
            if st is None:
                st = APStatus(ap_id=ap_id, running=True)
                self._status[ap_id] = st
            st.running = True
            st.last_error = ""

    def stop(self, ap_id: int):
        with self._lock:
            self._running_flags[ap_id] = False
            st = self._status.get(ap_id)
            if st is None:
                st = APStatus(ap_id=ap_id, running=False)
                self._status[ap_id] = st
            st.running = False
            st.in_flight = False

    def get_status(self, ap_id: int) -> APStatus:
        with self._lock:
            st = self._status.get(ap_id)
            if st is None:
                st = APStatus(ap_id=ap_id, running=False)
                self._status[ap_id] = st
            return APStatus(**st.__dict__)

    def shutdown(self):
        self._stop_evt.set()
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


    def _scheduler_loop(self):
        while not self._stop_evt.is_set():
            try:
                if self._index.needs_refresh():
                    self._index.refresh()

                ap_ids = []
                with self._lock:
                    for ap_id, running in self._running_flags.items():
                        if running:
                            ap_ids.append(ap_id)

                now = time.time()
                for ap_id in ap_ids:
                    st = self.get_status(ap_id)
                    if st.in_flight:
                        continue
                    if st.next_allowed_ts > now:
                        continue
                    if (now - st.last_check_ts) < ANALYSIS_INTERVAL_SEC:
                        continue

                    with self._lock:
                        real = self._status.get(ap_id)
                        if real is None:
                            real = APStatus(ap_id=ap_id, running=True)
                            self._status[ap_id] = real
                        if real.in_flight:
                            continue
                        real.in_flight = True
                        real.last_check_ts = now

                    self._executor.submit(self._process_once, ap_id)

            except Exception:
                pass

            time.sleep(0.15)

    def _process_once(self, ap_id: int):
        db = SessionLocal()
        try:
            ap: AccessPoint = db.get(AccessPoint, ap_id)
            if not ap or not ap.is_active:
                self._set_error(ap_id, "Точка доступа не найдена или неактивна.")
                return

            if not ap.camera or not ap.camera.is_active:
                self._set_error(ap_id, "У точки доступа нет активной камеры.")
                return

            # гарантируем, что camera_manager читает поток
            camera_manager.ensure_started(
                key=ap.access_point_id,
                source_type=ap.camera.source_type,
                source=ap.camera.source,
            )

            frame = camera_manager.get_latest_frame(ap.access_point_id)
            if frame is None:
                self._set_error(ap_id, "Кадр от камеры ещё не получен.")
                return

            # Детект лиц
            face_app = get_face_app()
            faces = face_app.get(frame)
            if not faces:
                # лица нет — событие не пишем
                self._set_status(ap_id, last_error="", last_decision="", last_subject="", last_similarity=0.0)
                return

            # Выбираем самое большое лицо
            best = None
            best_area = -1.0
            for f in faces:
                x1, y1, x2, y2 = f.bbox
                area = float(max(1.0, (x2 - x1)) * max(1.0, (y2 - y1)))
                if area > best_area:
                    best_area = area
                    best = f

            if best is None:
                return

            probe_emb = np.asarray(best.embedding, dtype=np.float32)

            # Match через кэш
            user_id, template_id, sim = self._index.match(probe_emb)

            # RBAC decision + причина
            decision, subject_name, reason_ru = self._decide(db, ap, user_id)

            # Управление устройством (и логирование для администратора)
            action = "none"
            device = "—"
            result = "—"
            msg = ""

            if decision == "ALLOW":
                action = "open"
                ok, msg, device = self._send_control(ap, "open")
                result = "ok" if ok else "fail"
                if not ok:
                    self._set_error(ap_id, f"ALLOW, но команда open не выполнена: {msg}")
            else:
                if ap.control_unit:
                    device = ap.control_unit.name
                result = "skipped"

            # details в формате: источник | распознано/unknown | DECISION: причина | sim | действие | устройство | результат
            src = "auto"
            who_tag = "распознано" if user_id is not None else "не распознано"
            sim_part = f"sim={sim:.3f}" if user_id is not None else "sim=—"
            details = (
                f"{src} | {who_tag} | {decision}: {reason_ru} | {sim_part} | "
                f"действие={action} | устройство={device} | результат={result}"
            )
            if msg:
                details += f" | сообщение={msg}"

            ev = AccessEvent(
                access_point_id=ap.access_point_id,
                user_id=user_id if user_id is not None else None,
                decision=decision,
                match_score=sim if user_id is not None else None,
                details=details,
            )
            db.add(ev)
            db.commit()

            # Cooldown
            now = time.time()
            cooldown = COOLDOWN_AFTER_ALLOW_SEC if decision == "ALLOW" else COOLDOWN_AFTER_EVENT_SEC

            with self._lock:
                st = self._status.get(ap_id)
                if st is None:
                    st = APStatus(ap_id=ap_id, running=True)
                    self._status[ap_id] = st
                st.last_event_ts = now
                st.next_allowed_ts = now + cooldown
                st.last_decision = decision
                st.last_subject = subject_name
                st.last_similarity = float(sim)

        except Exception as e:
            self._set_error(ap_id, str(e))
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
            with self._lock:
                st = self._status.get(ap_id)
                if st is None:
                    st = APStatus(ap_id=ap_id, running=True)
                    self._status[ap_id] = st
                st.in_flight = False

    def _decide(self, db, ap: AccessPoint, user_id: Optional[int]) -> Tuple[str, str, str]:
        """
        Возвращает (decision, subject_name, reason_ru)
        """
        if user_id is None:
            return "UNKNOWN", "UNKNOWN", "Лицо отсутствует в базе (не найдено совпадение)"

        user: User = db.get(User, user_id)
        if not user:
            return "UNKNOWN", "UNKNOWN", "Пользователь не найден в базе"

        if not user.is_active:
            return "DENY", user.full_name, "Пользователь отключён (is_active = false)"

        role_ids = [r.role_id for r in user.roles] if user.roles else []
        if not role_ids:
            return "DENY", user.full_name, "Пользователю не назначены роли"

        perms = (
            db.query(RoleZonePermission)
            .filter(RoleZonePermission.role_id.in_(role_ids))
            .filter(RoleZonePermission.zone_id == ap.zone_id)
            .all()
        )
        if not perms:
            return "DENY", user.full_name, "Нет правил доступа для этой зоны (роль-зона)"

        if any(p.is_allowed for p in perms):
            return "ALLOW", user.full_name, "Доступ разрешён по правилам роль-зона"

        return "DENY", user.full_name, "Доступ запрещён по правилам роль-зона"

    def _send_control(self, ap: AccessPoint, cmd: str) -> Tuple[bool, str, str]:
        """
        Возвращает (ok, msg, unit_name)
        """
        if not ap.control_unit:
            return False, "Нет исполнительного устройства", "—"

        unit = ap.control_unit
        unit_name = unit.name

        if not unit.is_active:
            return False, "Исполнительное устройство неактивно", unit_name

        if unit.unit_type == "stub":
            return True, "STUB ok", unit_name

        if unit.unit_type == "http":
            if not unit.endpoint:
                return False, "Устройство HTTP: endpoint не задан", unit_name
            try:
                import requests
                url = unit.endpoint.rstrip("/") + f"/{cmd}"
                r = requests.post(url, timeout=2.0)
                if 200 <= r.status_code < 300:
                    return True, f"HTTP {r.status_code}", unit_name
                return False, f"HTTP {r.status_code}", unit_name
            except Exception as e:
                return False, str(e), unit_name

        return False, f"Неизвестный тип устройства: {unit.unit_type}", unit_name

    def _set_error(self, ap_id: int, msg: str):
        with self._lock:
            st = self._status.get(ap_id)
            if st is None:
                st = APStatus(ap_id=ap_id, running=self._running_flags.get(ap_id, False))
                self._status[ap_id] = st
            st.last_error = msg

    def _set_status(self, ap_id: int, last_error: str, last_decision: str, last_subject: str, last_similarity: float):
        with self._lock:
            st = self._status.get(ap_id)
            if st is None:
                st = APStatus(ap_id=ap_id, running=self._running_flags.get(ap_id, False))
                self._status[ap_id] = st
            st.last_error = last_error
            st.last_decision = last_decision
            st.last_subject = last_subject
            st.last_similarity = float(last_similarity)


access_worker_manager = AccessWorkerManager()