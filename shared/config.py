# ============================================================
# FILE: shared/config.py
# PURPOSE: Central application settings loaded from .env file.
#          Used by all 3 use cases and the FastAPI main server.
# USE CASE: All (Shared)
#
# HOW IT WORKS:
#   - Uses pydantic-settings BaseSettings to load values from .env
#   - All settings have safe defaults so the app starts without .env
#   - Properties compute RTSP URL from components when rtsp_url is blank
#
# DEBUG TIPS:
#   - Settings not loading from .env?
#       → Check .env is in the PROJECT ROOT (same folder as main.py).
#       → Confirm variable names match exactly (case-insensitive).
#       → Run: python -c "from shared.config import settings; print(settings.source)"
#   - RTSP stream not connecting?
#       → Check RTSP_URL or RTSP_IP + RTSP_USERNAME + RTSP_PASSWORD in .env
#       → settings.source returns the computed RTSP URL — log it on startup.
#   - Face recognition not matching?
#       → Check FACE_MATCH_THRESHOLD (default 0.40). Lower = more permissive.
#       → Check FACE_V2_ENABLED=true in .env.
#   - Alerts too frequent?
#       → Increase ALERT_COOLDOWN in .env (default 30s).
#   - Evidence not saving?
#       → Check EVIDENCE_DIR in .env (default "evidence").
#       → Path is relative to project root unless absolute.
#
# KEY SETTINGS:
#   VIDEO_SOURCE       = "rtsp" | "webcam" | "file"
#   RTSP_URL           = Full RTSP URL (optional if using RTSP_IP)
#   RTSP_IP / RTSP_PORT / RTSP_USERNAME / RTSP_PASSWORD = RTSP auth components
#   FACE_MATCH_THRESHOLD = Cosine similarity threshold for face recognition (0.0–1.0)
#   ALERT_COOLDOWN     = Seconds between repeated alerts for the same person+event
#   EVIDENCE_DIR       = Directory for saving intrusion evidence images
#   DATABASE_URL       = SQLAlchemy DB URL (default: sqlite:///./perimeter_monitor.db)
# ============================================================

from pathlib import Path
from urllib.parse import quote, unquote
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # --- Camera Identity ---
    camera_name: str = "Camera 14"
    nvr_name: str = "RTSP Stream"
    camera_location: str = "IT Furnace"

    # --- RTSP Source ---
    rtsp_url: str = ""
    rtsp_username: str = ""
    rtsp_password: str = ""
    rtsp_ip: str = ""
    rtsp_port: int = 554
    rtsp_channel: int = 1
    rtsp_subtype: int = 0

    # --- Dual Gate Camera (Channel 1 = IN, Channel 2 = OUT) ---
    dual_gate_cameras: bool = True
    rtsp_url_in: str = ""
    rtsp_channel_in: int = 1

    # --- Video Source Mode ---
    video_source: str = "rtsp"
    webcam_index: int = 0
    sample_video_path: str = ""
    sample_fallback_enabled: bool = True
    sample_fallback_after: float = 15.0

    # --- Camera Connection Tuning ---
    camera_connect_timeout: float = 5.0
    camera_reconnect_interval: float = 2.0
    camera_auto_reconnect: bool = True
    camera_auto_start: bool = True
    camera_reconnect_delay: float = 3.0
    camera_max_reconnect_delay: float = 30.0
    camera_read_timeout: int = 10000
    camera_open_timeout: int = 10000

    # --- YOLO Detection ---
    model_path: str = "models/yolov8n.pt"
    person_confidence: float = 0.30
    iou_threshold: float = 0.45
    inference_fps: float = 3.0

    # --- Face Recognition v2 (InsightFace + multi-frame) ---
    face_v2_enabled: bool = True
    face_max_photos: int = 15
    face_match_threshold: float = 0.40
    face_match_margin: float = 0.05
    face_votes_required: int = 1
    face_min_person_height: int = 80
    face_min_face_px: int = 28
    face_min_det_score: float = 0.5
    face_min_blur: float = 15.0
    face_unknown_attempts: int = 5
    face_retry_interval: float = 0.6
    face_max_per_cycle: int = 1

    # --- Perimeter Fencing (Use Case 1) ---
    alert_cooldown: int = 30
    boundary_mode: str = "crossing"
    approach_distance: int = 35

    # --- Database ---
    database_url: str = "sqlite:///./perimeter_monitor.db"

    # --- Notifications ---
    ntfy_enabled: bool = False
    ntfy_topic: str = ""

    # --- Security ---
    admin_token: str = "change-this-before-exposing-admin-api"

    # --- Evidence Storage ---
    evidence_dir: str = "evidence"

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def source_kind(self):
        """Determine the camera source type from VIDEO_SOURCE setting."""
        kind = self.video_source.strip().lower()
        if kind.isdigit() or kind in ("webcam", "camera"):
            return "webcam"
        if kind in ("rtsp", "webcam"):
            return kind
        if kind in ("video", "file"):
            return "file"
        return "file"

    @property
    def source(self):
        """Compute the camera source URL/index from settings."""
        kind = self.source_kind
        if kind == "rtsp":
            if self.rtsp_url.strip():
                return self.rtsp_url.strip()
            if self.rtsp_ip.strip():
                username = quote(unquote(self.rtsp_username), safe="")
                password = quote(unquote(self.rtsp_password), safe="")
                auth = f"{username}:{password}@" if username or password else ""
                return (
                    f"rtsp://{auth}{self.rtsp_ip.strip()}:{self.rtsp_port}"
                    f"/cam/realmonitor?channel={self.rtsp_channel}&subtype={self.rtsp_subtype}"
                )
            return ""
        if kind == "webcam":
            return self.video_source if self.video_source.strip().isdigit() else str(self.webcam_index)
        if kind == "file":
            return self.sample_video_path if self.video_source.strip().lower() in ("file", "video") else self.video_source
        return self.video_source

    @property
    def source_in(self):
        """RTSP URL for the dedicated Gate 3 IN Camera (Channel 1)."""
        if not self.dual_gate_cameras or self.source_kind != "rtsp":
            return ""
        if self.rtsp_url_in.strip():
            return self.rtsp_url_in.strip()
        if self.rtsp_ip.strip():
            username = quote(unquote(self.rtsp_username), safe="")
            password = quote(unquote(self.rtsp_password), safe="")
            auth = f"{username}:{password}@" if username or password else ""
            return (
                f"rtsp://{auth}{self.rtsp_ip.strip()}:{self.rtsp_port}"
                f"/cam/realmonitor?channel={self.rtsp_channel_in}&subtype={self.rtsp_subtype}"
            )
        return ""


settings = Settings()
