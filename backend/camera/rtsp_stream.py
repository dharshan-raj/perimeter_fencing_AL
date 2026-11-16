"""Single-owner OpenCV capture for RTSP, webcam, and video files."""
import os
import logging
import time
import cv2
from ..config import settings

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

log = logging.getLogger(__name__)

class RTSPStream:
    """Capture wrapper retained under its old name for compatibility."""
    def __init__(self, source, source_kind=None):
        self.source = source
        self.source_kind = source_kind or self._guess_kind(source)
        self.capture = None
        self.connected = False
        self.last_frame = None
        self.last_error = ""
        self._next_open = 0.0
        self.retry_attempt = 0
        self.last_retry_delay = 0.0

    @property
    def retry_wait_seconds(self):
        return max(0.0, self._next_open - time.monotonic())

    def _schedule_retry(self):
        initial = max(0.1, float(settings.camera_reconnect_delay))
        maximum = max(initial, float(settings.camera_max_reconnect_delay))
        self.retry_attempt += 1
        delay = initial
        for _ in range(min(self.retry_attempt - 1, 32)):
            delay = min(delay * 2, maximum)
        self.last_retry_delay = delay
        self._next_open = time.monotonic() + delay
        log.warning("Camera %s disconnected; retry %d in %.1f seconds: %s",
                    self.source_kind, self.retry_attempt, delay, self.last_error)

    def _reset_retry(self):
        if self.retry_attempt:
            log.info("Camera %s reconnected; retry backoff reset", self.source_kind)
        self.retry_attempt = 0
        self.last_retry_delay = 0.0
        self._next_open = 0.0

    @staticmethod
    def _guess_kind(source):
        value = str(source).lower()
        if value.startswith("rtsp://"): return "rtsp"
        if value.isdigit(): return "webcam"
        return "file"

    def _open(self):
        if not self.source:
            self.last_error = f"No URL configured for {self.source_kind} camera source"
            return False
        if time.monotonic() < self._next_open: return False
        source = int(self.source) if self.source_kind == "webcam" and str(self.source).isdigit() else str(self.source)
        backend = cv2.CAP_DSHOW if self.source_kind == "webcam" and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_FFMPEG
        log.info("Opening %s camera source (attempt %d)", self.source_kind, self.retry_attempt + 1)
        try:
            if self.source_kind == "rtsp":
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
                params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(settings.camera_open_timeout),
                          cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(settings.camera_read_timeout)]
                try:
                    self.capture = cv2.VideoCapture(source, backend, params)
                except (TypeError, cv2.error):
                    # Older OpenCV builds do not accept timeout parameters.
                    log.warning("OpenCV timeout parameters are unsupported; using the standard capture call")
                    self.capture = cv2.VideoCapture(source, backend)
            else:
                self.capture = cv2.VideoCapture(source, backend)
        except Exception as exc:
            self.last_error = f"OpenCV could not open the configured video source: {exc}"
            self.release()
            self._schedule_retry()
            return False
        if self.capture is not None and self.capture.isOpened():
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.last_error = ""
            return True
        self.last_error = "OpenCV could not open the configured video source"
        self.release()
        self._schedule_retry()
        return False

    def read(self):
        if self.capture is None and not self._open():
            self.connected = False
            return False, None
        try:
            ok, frame = self.capture.read()
        except Exception as exc:
            ok, frame = False, None
            self.last_error = f"OpenCV frame read failed: {exc}"
        if ok and frame is not None:
            self.connected = True
            self.last_frame = time.time()
            self.last_error = ""
            self._reset_retry()
            return True, frame
        self.connected = False
        if not self.last_error:
            self.last_error = "Video stream ended or returned an invalid frame"
        self.release()
        self._schedule_retry()
        return False, None

    def test_connection(self, timeout=None):
        """Open the configured source and verify an actual decoded frame, then close it."""
        deadline = time.monotonic() + (timeout or settings.camera_connect_timeout)
        try:
            while time.monotonic() < deadline:
                ok, frame = self.read()
                if ok and frame is not None:
                    return {"connected": True, "tested": True, "width": int(frame.shape[1]),
                            "height": int(frame.shape[0]), "source_type": self.source_kind, "error": None}
                if self.source_kind == "webcam" or not self.source:
                    break
                wait = min(self.retry_wait_seconds, max(0.0, deadline - time.monotonic()))
                if wait:
                    time.sleep(wait)
            return {"connected": False, "tested": True, "width": None, "height": None,
                    "source_type": self.source_kind, "error": self.last_error or "No decodable frame before timeout"}
        finally:
            self.release()

    def release(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.connected = False


def configured_source():
    kind = settings.source_kind
    source = settings.source
    if kind == "rtsp" and not source:
        return None, kind, "RTSP_URL is not configured"
    return source, kind, None
