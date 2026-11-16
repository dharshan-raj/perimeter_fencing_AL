import numpy as np

from backend.camera.rtsp_stream import RTSPStream
from backend.config import settings


def test_retry_delay_doubles_and_caps(monkeypatch):
    monkeypatch.setattr(settings, "camera_reconnect_delay", 3.0)
    monkeypatch.setattr(settings, "camera_max_reconnect_delay", 30.0)
    stream = RTSPStream("rtsp://camera.example/stream", "rtsp")

    actual = []
    for _ in range(6):
        stream._schedule_retry()
        actual.append(stream.last_retry_delay)

    assert actual == [3, 6, 12, 24, 30, 30]


def test_successful_frame_resets_retry_backoff(monkeypatch):
    class Capture:
        def isOpened(self):
            return True

        def set(self, *_):
            return True

        def read(self):
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def release(self):
            pass

    capture = Capture()
    monkeypatch.setattr("backend.camera.rtsp_stream.cv2.VideoCapture", lambda *args: capture)
    monkeypatch.setattr(settings, "camera_open_timeout", 1000)
    monkeypatch.setattr(settings, "camera_read_timeout", 1000)
    stream = RTSPStream("rtsp://camera.example/stream", "rtsp")
    stream.retry_attempt = 4
    stream.last_retry_delay = 30

    ok, frame = stream.read()

    assert ok and frame is not None
    assert stream.connected is True
    assert stream.retry_attempt == 0
    assert stream.last_retry_delay == 0


def test_failed_frame_releases_capture_and_schedules_retry(monkeypatch):
    class Capture:
        released = False

        def isOpened(self):
            return True

        def set(self, *_):
            return True

        def read(self):
            return False, None

        def release(self):
            self.released = True

    capture = Capture()
    monkeypatch.setattr("backend.camera.rtsp_stream.cv2.VideoCapture", lambda *args: capture)
    monkeypatch.setattr(settings, "camera_open_timeout", 1000)
    monkeypatch.setattr(settings, "camera_read_timeout", 1000)
    monkeypatch.setattr(settings, "camera_reconnect_delay", 3.0)
    monkeypatch.setattr(settings, "camera_max_reconnect_delay", 30.0)
    stream = RTSPStream("rtsp://camera.example/stream", "rtsp")

    ok, frame = stream.read()

    assert not ok and frame is None
    assert capture.released is True
    assert stream.retry_attempt == 1
    assert stream.retry_wait_seconds > 0


def test_stream_recovers_after_a_failed_open(monkeypatch):
    class Capture:
        def __init__(self, opened):
            self.opened = opened

        def isOpened(self):
            return self.opened

        def set(self, *_):
            return True

        def read(self):
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def release(self):
            pass

    attempts = iter([Capture(False), Capture(True)])
    monkeypatch.setattr("backend.camera.rtsp_stream.cv2.VideoCapture", lambda *args: next(attempts))
    monkeypatch.setattr(settings, "camera_open_timeout", 1000)
    monkeypatch.setattr(settings, "camera_read_timeout", 1000)
    monkeypatch.setattr(settings, "camera_reconnect_delay", 3.0)
    monkeypatch.setattr(settings, "camera_max_reconnect_delay", 30.0)
    stream = RTSPStream("rtsp://camera.example/stream", "rtsp")

    assert stream.read() == (False, None)
    assert stream.retry_attempt == 1
    stream._next_open = 0  # Simulate the configured retry delay expiring.
    ok, frame = stream.read()

    assert ok and frame is not None
    assert stream.connected is True
    assert stream.retry_attempt == 0
