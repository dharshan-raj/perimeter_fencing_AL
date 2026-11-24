import threading, time, logging, cv2, math
from datetime import datetime, timezone
from pathlib import Path
from ..config import settings
from ..database import SessionLocal
from ..models import Camera, Alert, DetectionLog, SystemLog, HeadcountEvent
from ..headcount.headcount_manager import HeadcountManager
from ..detection.detector import PersonDetector
from ..detection.zone_manager import ZoneManager
from ..detection.intrusion_detector import IntrusionDetector
from .rtsp_stream import RTSPStream, configured_source
from ..services.evidence_service import save

log = logging.getLogger(__name__)


class CameraManager:
    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.status = "Disconnected"
        self.video_status = "Disconnected"
        self.active_source = None
        self.stream = None
        self.detector = None
        self.zone = ZoneManager()
        self.last_frame = None
        self.last_frame_timestamp = None
        self.people = []
        self.total_people = 0
        self.seen_person_ids = set()
        self.crossings = 0
        self.reconnect_attempt = 0
        self.retry_in_seconds = 0.0
        self.connection_lock = threading.Lock()
        # Headcount uses the SAME detected people and frames as perimeter monitoring.
        # Its virtual counting line is configured independently in config/gates.json.
        self.headcount = HeadcountManager()
        # ── Face recognition (loaded lazily after first frame) ──────────────
        self.face_registry = None
        self.track_identifier = None          # multi-frame identity (face v2)
        self._face_registry_loaded = False   # True once load attempted (even if failed)
        self._face_cache: dict = {}           # {tracking_id: (name, timestamp)}
        self._face_cache_ttl = 3.0           # re-recognise each track every 3 s
        # ── Companion Gate 3 IN Camera (Channel 1) ──────────────────────────
        self.in_thread = None
        self.in_stream = None
        self.in_status = "Disconnected"
        self.in_video_status = "Disconnected"
        self.last_in_frame = None
        self.in_people = []
        self.in_track_identifier = None
        self._in_face_cache: dict = {}

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self.stop_event.clear()
        self.status = "Reconnecting" if configured_source()[0] else "Disconnected"
        self.video_status = "Disconnected"
        self.reconnect_attempt = 0
        self.retry_in_seconds = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True, name="camera-processor")
        self.thread.start()
        if settings.dual_gate_cameras and settings.source_in and settings.source_in != settings.source:
            self.in_status = "Reconnecting"
            self.in_thread = threading.Thread(target=self._run_in_camera, daemon=True, name="camera-in-processor")
            self.in_thread.start()
        return True

    def stop(self):
        self.stop_event.set()

    def test_connection(self):
        """Never opens another capture while the processing worker owns the camera."""
        with self.connection_lock:
            if self.thread and self.thread.is_alive() and self.stream is not None:
                fresh = self.stream.connected and self.stream.last_frame and time.time() - self.stream.last_frame < 10
                return {"connected": bool(fresh), "tested": bool(self.stream.last_frame),
                        "source_type": self.active_source or settings.source_kind,
                        "error": None if fresh else (self.stream.last_error or "Camera worker has not decoded a recent frame")}
            source, kind, error = configured_source()
            if error:
                return {"connected": False, "tested": False, "source_type": kind, "error": error}
            probe = RTSPStream(source, kind)
            return probe.test_connection(settings.camera_connect_timeout)

    def _log_camera_disconnect(self, db, publish_from_thread):
        db.add(SystemLog(log_level="WARNING", message="Camera/video stream disconnected; reconnect attempts continuing"))
        db.commit()
        publish_from_thread({"event_type": "Camera Disconnected", "severity": "WARNING"})

    def _run(self):
        from ..main import publish_from_thread

        db = None
        primary_stream = None
        sample_stream = None
        self.total_people = 0
        self.seen_person_ids.clear()
        source, kind, missing = configured_source()
        if missing:
            log.warning("Camera source unavailable: %s", missing)
        if source:
            primary_stream = RTSPStream(source, kind)
        stream = primary_stream
        using_sample = False
        with self.connection_lock:
            self.stream = primary_stream
        self.status = "Reconnecting" if primary_stream and settings.camera_auto_reconnect else "Disconnected"
        self.video_status = "Disconnected"
        self.active_source = kind if primary_stream else None
        self.reconnect_attempt = 0
        self.retry_in_seconds = 0.0

        detector = None
        cam_id = None
        intrusion = IntrusionDetector(self.zone, settings.boundary_mode, settings.approach_distance)
        last_inference = 0.0
        video_was_connected = False
        camera_was_connected = False
        camera_connected_once = False
        selected_at = time.monotonic()
        next_detector_retry = 0.0

        try:
            db = SessionLocal()
            camera = db.query(Camera).filter_by(camera_name=settings.camera_name).first()
            if not camera:
                camera = Camera(camera_name=settings.camera_name, nvr_name=settings.nvr_name, location=settings.camera_location)
                db.add(camera)
                db.commit()
            cam_id = camera.id

            while not self.stop_event.is_set():
                if primary_stream is None:
                    fallback = Path(settings.sample_video_path) if settings.sample_video_path else None
                    if (settings.sample_fallback_enabled and fallback and fallback.is_file()
                            and time.monotonic() - selected_at >= settings.sample_fallback_after):
                        sample_stream = RTSPStream(str(fallback), "file")
                        stream = sample_stream
                        using_sample = True
                        self.active_source = "sample"
                        log.warning("Using configured development sample video; RTSP URL is not configured")
                    else:
                        self.stop_event.wait(1.0)
                        continue

                if using_sample and primary_stream is not None and settings.camera_auto_reconnect:
                    camera_ok, camera_frame = primary_stream.read()
                    self.reconnect_attempt = primary_stream.retry_attempt
                    self.retry_in_seconds = primary_stream.retry_wait_seconds
                    if camera_ok and camera_frame is not None:
                        if sample_stream:
                            sample_stream.release()
                        stream = primary_stream
                        sample_stream = None
                        using_sample = False
                        ok, frame = True, camera_frame
                        log.info("RTSP camera reconnected while sample fallback was active")
                    else:
                        if camera_was_connected:
                            self._log_camera_disconnect(db, publish_from_thread)
                            camera_was_connected = False
                        self.status = "Reconnecting"
                        ok, frame = sample_stream.read()
                else:
                    ok, frame = stream.read()

                if not ok or frame is None:
                    self.video_status = "Disconnected"
                    self.last_frame = None
                    self.last_frame_timestamp = None
                    self.people = []
                    failed_stream = sample_stream if using_sample else primary_stream
                    if not using_sample:
                        self.status = "Reconnecting" if settings.camera_auto_reconnect else "Disconnected"
                        self.reconnect_attempt = failed_stream.retry_attempt if failed_stream else 0
                        self.retry_in_seconds = failed_stream.retry_wait_seconds if failed_stream else 0.0
                        if camera_was_connected:
                            self._log_camera_disconnect(db, publish_from_thread)
                            camera_was_connected = False
                    if (not using_sample and settings.sample_fallback_enabled and settings.sample_video_path
                            and Path(settings.sample_video_path).is_file()
                            and time.monotonic() - selected_at >= settings.sample_fallback_after):
                        sample_stream = RTSPStream(settings.sample_video_path, "file")
                        stream = sample_stream
                        using_sample = True
                        self.active_source = "sample"
                        log.warning("Using configured development sample video after camera source timeout; RTSP retries continue")
                        continue
                    if not settings.camera_auto_reconnect and not using_sample:
                        break
                    if not using_sample and failed_stream:
                        wait = max(0.1, failed_stream.retry_wait_seconds)
                        if self.stop_event.wait(wait):
                            break
                    elif using_sample and sample_stream:
                        wait = max(0.1, sample_stream.retry_wait_seconds)
                        if self.stop_event.wait(min(wait, 1.0)):
                            break
                    continue

                self.video_status = "Connected"
                self.last_frame = frame.copy()
                self.last_frame_timestamp = datetime.now(timezone.utc).isoformat()
                self.active_source = "sample" if using_sample else kind
                if not using_sample and kind in ("rtsp", "webcam"):
                    self.status = "Connected"
                    self.reconnect_attempt = 0
                    self.retry_in_seconds = 0.0
                    if not camera_was_connected:
                        if camera_connected_once:
                            log.info("Camera reconnected successfully; resuming detection")
                            db.add(SystemLog(log_level="INFO", message="Camera reconnected successfully; monitoring resumed"))
                            db.commit()
                            publish_from_thread({"event_type": "Camera Reconnected", "severity": "INFO"})
                        else:
                            log.info("Camera connected successfully")
                            db.add(SystemLog(log_level="INFO", message="Camera connected"))
                            db.commit()
                        camera_connected_once = True
                    camera_was_connected = True
                elif using_sample and primary_stream and settings.camera_auto_reconnect:
                    self.status = "Reconnecting"
                else:
                    self.status = "Disconnected"

                if not video_was_connected:
                    source_description = "development sample video" if using_sample else "video source"
                    log.info("%s connected", source_description.capitalize())
                    db.add(SystemLog(log_level="INFO", message=f"{source_description.capitalize()} connected"))
                    db.commit()
                video_was_connected = True

                 # Initialize YOLO after the first valid decoded frame, then reuse it.
                if detector is None:
                    if time.monotonic() < next_detector_retry:
                        self.stop_event.wait(0.1)
                        continue
                    try:
                        detector = PersonDetector()
                        self.detector = detector
                    except Exception as exc:
                        log.exception("Could not initialize person detector")
                        db.add(SystemLog(log_level="ERROR", message="Detector initialization failed: " + str(exc)[:300]))
                        db.commit()
                        next_detector_retry = time.monotonic() + 10
                        self.stop_event.wait(0.1)
                        continue

                # ── Lazy-load face registry once detector is ready ──────────
                if not self._face_registry_loaded:
                    try:
                        from ..face_recognition.employee_registry import EmployeeRegistry
                        registry = EmployeeRegistry("backend/employee_face")
                        registry.load_employees(max_photos_per_employee=settings.face_max_photos)
                        self.face_registry = registry
                        if settings.face_v2_enabled:
                            try:
                                from ..face_recognition.track_identifier import TrackIdentifier
                                self.track_identifier = TrackIdentifier.from_settings(registry, settings)
                                log.info("Face recognition v2 (multi-frame) enabled")
                            except Exception as exc:
                                log.warning("Face recognition v2 unavailable, using v1: %s", exc)
                        log.info(
                            "Employee face registry loaded: %d employees",
                            len(registry.employee_embeddings),
                        )
                    except Exception as exc:
                        log.warning("Face recognition registry could not load: %s", exc)
                    finally:
                        self._face_registry_loaded = True  # don't retry every frame

                if time.time() - last_inference < 1 / max(settings.inference_fps, 0.1):
                    continue
                last_inference = time.time()
                try:
                    people = detector.detect_track(frame)
                    self.people = people
                except Exception as exc:
                    log.exception("Video processing failed")
                    db.add(SystemLog(log_level="ERROR", message="Video processing failed: " + str(exc)[:300]))
                    db.commit()
                    continue

                # ── Per-person face recognition (cached per tracking-ID) ────
                _now = time.time()
                _v2_done = False
                if self.track_identifier is not None:
                    try:
                        self.track_identifier.update_async(people, frame, _now)
                        for _p in people:
                            if _p.get("identity_state") == "IDENTIFIED":
                                # Keeps the Gate 3 attendance fallback lookup working.
                                self._face_cache[_p["id"]] = (_p["name"], _now)
                        _v2_done = True
                    except Exception:
                        log.exception("Face recognition v2 failed; falling back to v1")
                for _person in ([] if _v2_done else people):
                    _tid = _person["id"]
                    _cached = self._face_cache.get(_tid)
                    # If this person is already recognized as an employee, keep the name!
                    # Do not re-run CPU face recognition on an already matched employee.
                    if _cached:
                        if _cached[0] != "Unknown":
                            _person["name"] = _cached[0]
                            continue
                        # If previously Unknown, only retry after cache TTL
                        if _now - _cached[1] < self._face_cache_ttl:
                            _person["name"] = _cached[0]
                            continue

                    if self.face_registry is not None:
                        try:
                            _x1, _y1, _x2, _y2 = _person["box"]
                            # Use the upper 45 % of the bounding box as the face region
                            _face_h = max(1, math.ceil((_y2 - _y1) * 0.45))
                            _face_crop = frame[
                                max(0, _y1) : _y1 + _face_h,
                                max(0, _x1) : max(_x1 + 1, _x2),
                            ]
                            if _face_crop.size > 0:
                                _result = self.face_registry.recognize_employee(_face_crop)
                                _name = (
                                    _result["employee_id"].capitalize()
                                    if _result["status"] == "MATCHED"
                                    else "Unknown"
                                )
                            else:
                                _name = "Unknown"
                        except Exception:
                            _name = "Unknown"
                    else:
                        _name = "Unknown"
                    self._face_cache[_tid] = (_name, _now)
                    _person["name"] = _name
                # Evict cache entries for tracks that are no longer visible
                _active_ids = {p["id"] for p in people}
                self._face_cache = {k: v for k, v in self._face_cache.items() if k in _active_ids}

                # ---------------------------------------------------------
                # NEW: GATE 3 HEADCOUNT PROCESSING
                # Reuses the exact same YOLO + ByteTrack detections. No second
                # camera capture or second YOLO inference is created.
                # HeadcountManager.process() returns only confirmed crossings.
                # ---------------------------------------------------------
                headcount_payloads = []
                try:
                    use_dual = bool(self.in_thread and self.in_thread.is_alive())
                    headcount_events = (
                        self.headcount.process_out(people=people, frame_shape=frame.shape)
                        if use_dual
                        else self.headcount.process(people=people, frame_shape=frame.shape)
                    ) or []

                    for event in headcount_events:
                        event_key = str(event.get("event_key") or f"{event.get('gate_name')}_{event.get('tracking_id')}_{event.get('direction')}_{int(time.time())}")

                        # Extra database-level duplicate check. The unique
                        # constraint on HeadcountEvent.event_key is the final guard.
                        already_saved = db.query(HeadcountEvent.id).filter_by(
                            event_key=event_key
                        ).first()
                        if already_saved:
                            continue

                        event_timestamp = event.get("event_timestamp")
                        if not isinstance(event_timestamp, datetime):
                            event_timestamp = datetime.now(timezone.utc)

                        # Match tracking ID to employee name from recognition
                        # Line counter returns tracking_id as str; detector ids are int.
                        _evt_tid = str(event.get("tracking_id"))
                        _emp_name = event.get("employee_name")
                        if not _emp_name:
                            for p in people:
                                if str(p["id"]) == _evt_tid:
                                    n = p.get("name")
                                    if n and n != "Unknown":
                                        _emp_name = n
                                    break
                        if not _emp_name:
                            for k, c in self._face_cache.items():
                                if str(k) == _evt_tid and c[0] and c[0] != "Unknown":
                                    _emp_name = c[0]
                                    break

                        db.add(HeadcountEvent(
                            camera_id=cam_id,
                            gate_name=event.get("gate_name", "Plant Entrance Gate 3"),
                            tracking_id=str(event["tracking_id"]),
                            employee_name=_emp_name,
                            direction=str(event["direction"]).upper(),
                            event_key=event_key,
                            confidence=event.get("confidence"),
                            event_timestamp=event_timestamp
                        ))

                        headcount_payloads.append({
                            "event_type": "Headcount Event",
                            "severity": "INFO",
                            "gate_name": event.get("gate_name", "Plant Entrance Gate 3"),
                            "camera_id": cam_id,
                            "tracking_id": str(event["tracking_id"]),
                            "employee_name": _emp_name,
                            "direction": str(event["direction"]).upper(),
                            "confidence": event.get("confidence"),
                            "event_timestamp": event_timestamp.isoformat()
                        })

                except Exception as exc:
                    # A headcount configuration/processing issue must not stop
                    # the existing perimeter intrusion detection pipeline.
                    log.exception("Gate 3 headcount processing failed")
                    db.add(SystemLog(
                        log_level="ERROR",
                        message="Headcount processing failed: " + str(exc)[:300]
                    ))

                for person in people:
                    tracking_id = person["id"]
                    if tracking_id not in self.seen_person_ids:
                        self.seen_person_ids.add(tracking_id)
                        self.total_people += 1
                    state = intrusion.evaluate(person, frame.shape, settings.alert_cooldown)
                    db.add(DetectionLog(camera_id=cam_id, tracking_id=str(tracking_id), confidence=person["confidence"],
                                        bounding_box=str(person["box"]), zone_status="Inside" if state["inside"] else "Outside"))
                    if not state["event"]:
                        continue
                    evidence = save(frame, person, self.zone)
                    critical = state["event"] != "Boundary Approach"
                    alert = Alert(camera_id=cam_id, person_tracking_id=str(tracking_id), event_type=state["event"],
                                  severity="CRITICAL" if critical else "WARNING", confidence=person["confidence"],
                                  zone_name=state["zone"], crossing_direction=state["direction"], evidence_path=evidence)
                    db.add(alert)
                    db.commit()
                    db.refresh(alert)
                    relative = Path(evidence).resolve().relative_to(Path(settings.evidence_dir).resolve()).as_posix()
                    payload = {"id": alert.id, "camera_name": settings.camera_name, "nvr_name": settings.nvr_name,
                               "location": settings.camera_location, "person_tracking_id": alert.person_tracking_id,
                               "event_type": alert.event_type, "severity": alert.severity, "confidence": alert.confidence,
                               "zone_name": alert.zone_name, "crossing_direction": alert.crossing_direction,
                               "evidence_path": "/api/evidence/" + relative, "alert_status": alert.alert_status,
                               "event_timestamp": datetime.now(timezone.utc).isoformat()}
                    if critical:
                        self.crossings += 1
                    publish_from_thread(payload, critical)
                db.commit()

                # Broadcast headcount events only after the database commit.
                for headcount_payload in headcount_payloads:
                    publish_from_thread(headcount_payload, False)

        except Exception as exc:
            log.exception("Camera worker stopped")
            if db:
                try:
                    db.add(SystemLog(log_level="ERROR", message=str(exc)[:500]))
                    db.commit()
                except Exception:
                    pass
        finally:
            if primary_stream:
                primary_stream.release()
            if sample_stream:
                sample_stream.release()
            with self.connection_lock:
                self.stream = None
            if db:
                db.close()
            self.people = []
            self.last_frame = None
            self.last_frame_timestamp = None
            self.video_status = "Disconnected"
            self.status = "Stopped" if self.stop_event.is_set() else "Disconnected"
            self.retry_in_seconds = 0.0
            log.info("Camera worker stopped with status %s", self.status)

    def _run_in_camera(self):
        """Dedicated worker for Gate 3 IN Camera (Channel 1)."""
        from ..main import publish_from_thread

        db = None
        stream = RTSPStream(settings.source_in, "rtsp")
        self.in_stream = stream
        detector = None
        last_inference = 0.0
        cam_id = None

        try:
            db = SessionLocal()
            camera = db.query(Camera).filter_by(camera_name=settings.camera_name).first()
            cam_id = camera.id if camera else 1

            while not self.stop_event.is_set():
                ok, frame = stream.read()
                if not ok or frame is None:
                    self.in_video_status = "Disconnected"
                    self.in_status = "Reconnecting"
                    self.in_people = []
                    if self.stop_event.wait(0.2):
                        break
                    continue

                self.in_video_status = "Connected"
                self.in_status = "Connected"
                self.last_in_frame = frame.copy()

                if detector is None:
                    try:
                        detector = PersonDetector()
                    except Exception:
                        self.stop_event.wait(1.0)
                        continue

                if self.in_track_identifier is None and self.face_registry is not None and settings.face_v2_enabled:
                    try:
                        from ..face_recognition.track_identifier import TrackIdentifier
                        self.in_track_identifier = TrackIdentifier.from_settings(self.face_registry, settings)
                    except Exception:
                        pass

                if time.time() - last_inference < 1 / max(settings.inference_fps, 0.1):
                    continue
                last_inference = time.time()

                try:
                    people = detector.detect_track(frame)
                    self.in_people = people
                except Exception:
                    continue

                _now = time.time()
                if self.in_track_identifier is not None:
                    try:
                        self.in_track_identifier.update_async(people, frame, _now)
                        for _p in people:
                            if _p.get("identity_state") == "IDENTIFIED":
                                self._in_face_cache[_p["id"]] = (_p["name"], _now)
                    except Exception:
                        pass

                try:
                    in_events = self.headcount.process_in(people=people, frame_shape=frame.shape) or []
                    payloads = []
                    for event in in_events:
                        event_key = str(event.get("event_key") or f"Gate3_CH1_{event.get('tracking_id')}_IN_{int(time.time())}")
                        if db.query(HeadcountEvent.id).filter_by(event_key=event_key).first():
                            continue
                        event_timestamp = event.get("event_timestamp")
                        if not isinstance(event_timestamp, datetime):
                            event_timestamp = datetime.now(timezone.utc)
                        _evt_tid = str(event.get("tracking_id"))
                        _emp_name = event.get("employee_name")
                        if not _emp_name:
                            for p in people:
                                if str(p["id"]) == _evt_tid and p.get("name") and p.get("name") != "Unknown":
                                    _emp_name = p.get("name")
                                    break
                        if not _emp_name:
                            for k, c in self._in_face_cache.items():
                                if str(k) == _evt_tid and c[0] and c[0] != "Unknown":
                                    _emp_name = c[0]
                                    break
                        db.add(HeadcountEvent(
                            camera_id=cam_id,
                            gate_name=event.get("gate_name", "Gate 3"),
                            tracking_id=_evt_tid,
                            employee_name=_emp_name,
                            direction="IN",
                            event_key=event_key,
                            confidence=event.get("confidence"),
                            event_timestamp=event_timestamp,
                        ))
                        payloads.append({
                            "event_type": "Headcount Event",
                            "severity": "INFO",
                            "gate_name": event.get("gate_name", "Gate 3"),
                            "camera_id": cam_id,
                            "tracking_id": _evt_tid,
                            "employee_name": _emp_name,
                            "direction": "IN",
                            "confidence": event.get("confidence"),
                            "event_timestamp": event_timestamp.isoformat(),
                        })
                    if payloads:
                        db.commit()
                        for pl in payloads:
                            publish_from_thread(pl, False)
                except Exception:
                    log.exception("Gate 3 IN camera processing failed")
        finally:
            stream.release()
            self.in_stream = None
            if db:
                db.close()
            self.in_people = []
            self.last_in_frame = None
            self.in_video_status = "Disconnected"
            self.in_status = "Stopped" if self.stop_event.is_set() else "Disconnected"


camera_manager = CameraManager()
