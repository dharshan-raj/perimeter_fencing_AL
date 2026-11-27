from shared.config import settings

def test_video_source_selects_rtsp_or_webcam(monkeypatch):
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "rtsp://admin:Cctv%402026@192.168.1.245:554/cam/realmonitor?channel=2&subtype=1")
    assert settings.source_kind == "rtsp"
    assert settings.source == "rtsp://admin:Cctv%402026@192.168.1.245:554/cam/realmonitor?channel=2&subtype=1"
    monkeypatch.setattr(settings, "video_source", "webcam")
    assert settings.source_kind == "webcam"
    assert settings.source == "0"


def test_rtsp_components_build_encoded_dahua_url(monkeypatch):
    monkeypatch.setattr(settings, "video_source", "rtsp")
    monkeypatch.setattr(settings, "rtsp_url", "")
    monkeypatch.setattr(settings, "rtsp_username", "admin")
    monkeypatch.setattr(settings, "rtsp_password", "Cctv@2026")
    monkeypatch.setattr(settings, "rtsp_ip", "192.168.1.245")
    monkeypatch.setattr(settings, "rtsp_port", 554)
    monkeypatch.setattr(settings, "rtsp_channel", 2)
    monkeypatch.setattr(settings, "rtsp_subtype", 1)

    assert settings.source == "rtsp://admin:Cctv%402026@192.168.1.245:554/cam/realmonitor?channel=2&subtype=1"
