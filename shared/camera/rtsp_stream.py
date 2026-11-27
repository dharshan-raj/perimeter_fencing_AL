# ============================================================
# FILE: shared/camera/rtsp_stream.py
# PURPOSE: Low-latency single-owner OpenCV capture thread for
#          RTSP cameras, webcams, and local video files.
#          Provides always-fresh frame access without frame buffering.
# USE CASE: All (Shared)
#
# HOW IT WORKS:
#   - A background _capture_loop thread owns VideoCapture exclusively.
#   - read() returns the most recently captured frame immediately.
#   - Old frames are overwritten (no queue buildup = no latency drift).
#   - Auto-reconnect with exponential backoff (3s → 30s max).
#
# DEBUG TIPS:
#   - Stream stuck / always returns False?
#       → Check RTSP URL is correct and reachable from server.
#       → Try: ffplay <rtsp_url> from command line to verify stream.
#       → Check RTSP_TRANSPORT env var (default "tcp"). Try "udp" for some cameras.
#   - High frame latency?
#       → fflags;nobuffer + max_delay;500000 is set for RTSP — verify OPENCV_FFMPEG_CAPTURE_OPTIONS.
#       → Reduce inference_fps in .env to match processing speed.
#   - Camera disconnects frequently?
#       → Check camera_reconnect_delay and camera_max_reconnect_delay in .env.
#       → Increase camera_read_timeout (default 10000ms).
#   - Webcam not detected?
#       → Check webcam_index in .env (default 0). Try index 1 or 2.
#       → On Windows, CAP_DSHOW is used automatically for webcams.
#   - File source loops incorrectly?
#       → RTSPStream("path/to/video.mp4", "file") — kind must be "file".
#
# DEPENDENCIES:
#   - shared/config.py  → settings.camera_* connection parameters
#   - cv2 (OpenCV)      → VideoCapture
# ============================================================

import os
import logging
import threading
import time
import cv2
from shared.config import settings

log = logging.getLogger(__name__)


class RTSPStream:
    """
    Thread-safe single-frame camera reader.

    Usage:
        stream = RTSPStream("rtsp://...", "rtsp")
        ok, frame = stream.read()   # always returns latest frame
        stream.release()            # stop capture thread
    """

    def __init__(self, source, source_kind=None):
        self.source = source
        self.source_kind = source_kind or self._guess_kind(source)
        self.capture = None
        self.connected = False
        self.last_frame = None
        self.last_error = ""
        self.retry_attempt = 0
        self.last_retry_delay = 0.0
        self._next_open = 0.0
        self._stop_event = threading.Event()
        self._thread = None
        self._condition = threading.Condition()
        self._latest_frame = None
        self._frame_timestamp = None
        self._started = False

    @staticmethod
    def _guess_kind(source):
        """Infer source kind from source string."""
        value = str(source).lower()
        if value.startswith("rtsp://"):
            return "rtsp"
        if value.isdigit():
            return "webcam"
        return "file"

    @property
    def retry_wait_seconds(self):
        return max(0.0, self._next_open - time.monotonic())

    @property
    def frame_age_ms(self):
        """Age of the most recently captured frame in milliseconds."""
        if self._frame_timestamp is None:
            return None
        return round((time.time() - self._frame_timestamp) * 1000, 2)

    def _schedule_retry(self):
        """Exponential backoff retry scheduling on connection failure."""
        initial = max(0.1, float(settings.camera_reconnect_delay))
        maximum = max(initial, float(settings.camera_max_reconnect_delay))
        self.retry_attempt += 1
        delay = initial
        for _ in range(min(self.retry_attempt - 1, 32)):
            delay = min(delay * 2, maximum)
        self.last_retry_delay = delay
        self._next_open = time.monotonic() + delay
        log.warning("Camera disconnected; retry %d in %.1f seconds: %s", self.retry_attempt, delay, self.last_error)

    def _reset_retry(self):
        if self.retry_attempt:
            log.info("Camera reconnected")
        self.retry_attempt = 0
        self.last_retry_delay = 0.0
        self._next_open = 0.0

    def _open(self):
        """
        Attempt to open the camera source.
        Returns True on success, False on failure (schedules retry).

        DEBUG: Always returns False?
               → Check source URL/path and camera_connect_timeout in .env.
               → For RTSP: verify the stream is reachable: ffplay <url>
        """
        if not self.source:
            self.last_error = "No camera source configured"
            return False
        if time.monotonic() < self._next_open:
            return False

        source = int(self.source) if self.source_kind == "webcam" and str(self.source).isdigit() else str(self.source)
        backend = cv2.CAP_DSHOW if self.source_kind == "webcam" and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_FFMPEG

        try:
            if self.source_kind == "rtsp":
                transport = os.getenv("RTSP_TRANSPORT", "tcp").lower()
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                    f"rtsp_transport;{transport}|fflags;nobuffer|flags;low_delay|max_delay;500000"
                )
                params = [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(settings.camera_open_timeout),
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(settings.camera_read_timeout),
                ]
                try:
                    self.capture = cv2.VideoCapture(source, backend, params)
                except (TypeError, cv2.error):
                    log.warning("OpenCV timeout parameters unsupported; retrying without params")
                    self.capture = cv2.VideoCapture(source, backend)
            else:
                self.capture = cv2.VideoCapture(source, backend)

            if not self.capture.isOpened():
                self.last_error = "Could not open camera source"
                self._close_capture()
                self._schedule_retry()
                return False

            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # minimal buffer for low latency
            self.connected = True
            self.last_error = ""
            log.info("Camera connected: %s", self.source_kind)
            return True

        except Exception as exc:
            self.last_error = f"Camera open error: {exc}"
            self._close_capture()
            self._schedule_retry()
            return False

    def _close_capture(self):
        if self.capture is not None:
            try:
                self.capture.release()
            except Exception:
                pass
            self.capture = None
        self.connected = False

    def _capture_loop(self):
        """Background thread: continuously reads frames from the camera."""
        while not self._stop_event.is_set():
            if self.capture is None:
                if not self._open():
                    self._stop_event.wait(0.05)
                    continue
            try:
                ok, frame = self.capture.read()
            except Exception as exc:
                ok, frame = False, None
                self.last_error = f"Frame read error: {exc}"

            if ok and frame is not None:
                ts = time.time()
                with self._condition:
                    self._latest_frame = frame
                    self._frame_timestamp = ts
                    self.last_frame = ts
                    self._condition.notify_all()
                self.connected = True
                self.last_error = ""
                self._reset_retry()
            else:
                self.connected = False
                if not self.last_error:
                    self.last_error = "Stream ended or returned an invalid frame"
                self._close_capture()
                self._schedule_retry()
                self._stop_event.wait(0.05)
        self._close_capture()

    def _start(self):
        if self._started:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, name="RTSP-Capture", daemon=True)
        self._thread.start()
        self._started = True

    def read(self):
        """
        Return the newest captured frame.
        Old frames are overwritten (not queued) — always returns the latest.

        Returns:
            (True, frame)  if a frame is available
            (False, None)  if no frame within 0.5s timeout
        """
        if not self._started:
            self._start()
        with self._condition:
            if self._latest_frame is None:
                self._condition.wait(timeout=0.5)
            if self._latest_frame is None:
                return False, None
            return True, self._latest_frame.copy()

    def test_connection(self, timeout=None):
        """
        Verify that the camera produces a decoded frame within timeout seconds.
        Used by the API test-connection endpoint.
        """
        timeout = timeout or settings.camera_connect_timeout
        deadline = time.monotonic() + timeout
        self._start()
        try:
            while time.monotonic() < deadline:
                with self._condition:
                    if self._latest_frame is not None:
                        frame = self._latest_frame.copy()
                        return {"connected": True, "tested": True, "width": int(frame.shape[1]), "height": int(frame.shape[0]), "source_type": self.source_kind, "error": None}
                if self._stop_event.wait(0.1):
                    break
            return {"connected": False, "tested": True, "width": None, "height": None, "source_type": self.source_kind, "error": self.last_error or "No decoded frame before timeout"}
        finally:
            self.release()

    def release(self):
        """Stop the capture thread and release the camera."""
        if not self._started:
            return
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None
        self._started = False
        self.connected = False
        with self._condition:
            self._latest_frame = None
            self._frame_timestamp = None


def configured_source():
    """
    Return (source, kind, error) from settings.
    Returns error string if source is not configured.

    DEBUG: Returns (None, 'rtsp', 'RTSP_URL is not configured')?
           → Set RTSP_URL or RTSP_IP in .env.
    """
    kind = settings.source_kind
    source = settings.source
    if kind == "rtsp" and not source:
        return None, kind, "RTSP_URL is not configured"
    return source, kind, None
