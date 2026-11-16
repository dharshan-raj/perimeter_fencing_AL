from backend.config import settings

def test_video_source_selects_rtsp_or_webcam(monkeypatch):
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "rtsp://nvr.example/stream")
    assert settings.source_kind == "rtsp"
    assert settings.source == "rtsp://nvr.example/stream"
    monkeypatch.setattr(settings, "video_source", "webcam")
    assert settings.source_kind == "webcam"
    assert settings.source == "0"


def test_rtsp_components_build_encoded_dahua_url(monkeypatch):
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "")
    monkeypatch.setattr(settings, "rtsp_username", "admin")
    monkeypatch.setattr(settings, "rtsp_password", "secret@word")
    monkeypatch.setattr(settings, "rtsp_ip", "192.168.1.245")
    monkeypatch.setattr(settings, "rtsp_port", 554)
    monkeypatch.setattr(settings, "rtsp_channel", 2)
    monkeypatch.setattr(settings, "rtsp_subtype", 1)

    assert settings.source == "rtsp://admin:secret%40word@192.168.1.245:554/cam/realmonitor?channel=2&subtype=1"
