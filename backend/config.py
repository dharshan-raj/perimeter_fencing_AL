from pathlib import Path
from urllib.parse import quote, unquote
from pydantic_settings import BaseSettings, SettingsConfigDict
ROOT = Path(__file__).resolve().parent.parent
class Settings(BaseSettings):
    camera_name: str = "Camera 14"
    nvr_name: str = "RTSP Stream"
    camera_location: str = "IT Furnace"
    rtsp_url: str = ""
    rtsp_username: str = ""
    rtsp_password: str = ""
    rtsp_ip: str = ""
    rtsp_port: int = 554
    rtsp_channel: int = 1
    rtsp_subtype: int = 0
    video_source: str = "rtsp"
    webcam_index: int = 0
    sample_video_path: str = ""
    sample_fallback_enabled: bool = True
    camera_connect_timeout: float = 5.0
    camera_reconnect_interval: float = 2.0
    camera_auto_reconnect: bool = True
    camera_auto_start: bool = True
    camera_reconnect_delay: float = 3.0
    camera_max_reconnect_delay: float = 30.0
    camera_read_timeout: int = 10000
    camera_open_timeout: int = 10000
    sample_fallback_after: float = 15.0
    model_path: str = "models/yolov8n.pt"
    person_confidence: float = 0.45
    iou_threshold: float = 0.45
    inference_fps: float = 8
    alert_cooldown: int = 30
    boundary_mode: str = "crossing"
    approach_distance: int = 35
    database_url: str = "sqlite:///./perimeter_monitor.db"
    ntfy_enabled: bool = False
    ntfy_topic: str = ""
    admin_token: str = "change-this-before-exposing-admin-api"
    evidence_dir: str = "evidence"
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", case_sensitive=False)
    @property
    def source_kind(self):
        kind = self.video_source.strip().lower()
        if kind.isdigit() or kind in ("webcam", "camera"): return "webcam"
        if kind in ("rtsp", "webcam"): return kind
        if kind in ("video", "file"): return "file"
        return "file"

    @property
    def source(self):
        kind = self.source_kind
        if kind == "rtsp":
            if self.rtsp_url.strip():
                return self.rtsp_url.strip()
            if self.rtsp_ip.strip():
                username = quote(unquote(self.rtsp_username), safe="")
                password = quote(unquote(self.rtsp_password), safe="")
                auth = f"{username}:{password}@" if username or password else ""
                return (f"rtsp://{auth}{self.rtsp_ip.strip()}:{self.rtsp_port}"
                        f"/cam/realmonitor?channel={self.rtsp_channel}&subtype={self.rtsp_subtype}")
            return ""
        if kind == "webcam": return self.video_source if self.video_source.strip().isdigit() else str(self.webcam_index)
        if kind == "file":
            return self.sample_video_path if self.video_source.strip().lower() in ("file", "video") else self.video_source
        return self.video_source
settings = Settings()
