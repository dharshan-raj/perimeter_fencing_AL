from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from backend.main import _utc_isoformat, app, camera_manager
from backend.config import settings


def test_utc_isoformat_marks_naive_database_timestamps_as_utc():
    stored_utc = datetime(2026, 11, 24, 12, 0, 0)
    assert _utc_isoformat(stored_utc) == "2026-11-24T12:00:00+00:00"


def test_utc_isoformat_normalizes_aware_timestamps():
    local_offset = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime(2026, 11, 24, 17, 30, 0, tzinfo=local_offset)
    assert _utc_isoformat(timestamp) == "2026-11-24T12:00:00+00:00"


def test_health(monkeypatch):
    monkeypatch.setattr(settings, "camera_auto_start", False)
    monkeypatch.setattr(camera_manager, "start", lambda: None)
    monkeypatch.setattr(camera_manager, "stop", lambda: None)
    with TestClient(app) as client:
        response=client.get("/api/health")
        assert response.status_code==200
        assert response.json()["status"]=="ok"

def test_camera_connection_does_not_claim_unconfigured_rtsp_is_online(monkeypatch):
    monkeypatch.setattr(settings, "camera_auto_start", False)
    monkeypatch.setattr(camera_manager, "start", lambda: None)
    monkeypatch.setattr(camera_manager, "stop", lambda: None)
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "")
    monkeypatch.setattr(settings, "rtsp_ip", "")
    with TestClient(app) as client:
        response=client.post("/api/cameras/14/test-connection",headers={"X-Admin-Token":settings.admin_token})
        assert response.status_code==200
        assert response.json()["connected"] is False
        assert response.json()["tested"] is False
        assert "RTSP_URL" in response.json()["error"]


def test_camera_worker_starts_automatically_for_configured_source(monkeypatch):
    started = []
    monkeypatch.setattr(settings, "camera_auto_start", True)
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "rtsp://nvr.example/stream")
    monkeypatch.setattr(camera_manager, "start", lambda: started.append(True))
    monkeypatch.setattr(camera_manager, "stop", lambda: None)

    with TestClient(app):
        pass

    assert started == [True]
