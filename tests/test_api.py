from fastapi.testclient import TestClient
from backend.main import app, camera_manager
from backend.config import settings

def test_health(monkeypatch):
    monkeypatch.setattr(settings, "camera_auto_start", False)
    with TestClient(app) as client:
        response=client.get("/api/health")
        assert response.status_code==200
        assert response.json()["status"]=="ok"

def test_camera_connection_does_not_claim_unconfigured_rtsp_is_online(monkeypatch):
    monkeypatch.setattr(settings, "camera_auto_start", False)
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
