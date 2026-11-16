# IT Furnace ? AI Perimeter Fencing Monitoring System

A modular Camera 14 monitoring application. FastAPI runs an isolated camera worker, OpenCV/FFmpeg reads an RTSP/NVR CCTV stream, webcam, or a configured sample video, Ultralytics YOLO detects and tracks class 0 (person) with ByteTrack, normalized polygon zones classify intrusions, SQLAlchemy stores event history, and a React dashboard receives live WebSocket events.

## Requirements

- Python 3.10+ and FFmpeg available to OpenCV
- Node.js 18+ / npm
- Network reachability from the backend computer to the CCTV/NVR RTSP stream

## Run locally

1. Create and activate a Python virtual environment, then install dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env`, set `VIDEO_SOURCE=rtsp`, and set `RTSP_URL` to the CCTV/NVR stream URL. For a local webcam use `VIDEO_SOURCE=webcam` and `WEBCAM_INDEX=0`.
3. Install and start the backend:

   ```powershell
   python start.py
   ```
4. In another terminal:

   ```powershell
   npm install
   npm run dev
   ```
5. Visit http://localhost:5173. When `CAMERA_AUTO_START=true` and a source is configured, the backend starts the camera worker automatically and keeps retrying failed RTSP connections. The authenticated camera start/stop endpoints remain available for manual control.

The worker tests its source by decoding a frame before it initializes or runs YOLO. Configure `SAMPLE_VIDEO_PATH` to a local recorded clip and keep `SAMPLE_FALLBACK_ENABLED=true` to use that clip after `SAMPLE_FALLBACK_AFTER` seconds if the CCTV/NVR cannot connect. The physical camera remains reported offline while the dashboard labels the displayed clip as sample video. `POST /api/cameras/14/test-connection` tests the configured source without starting YOLO and reuses the worker connection if monitoring is active.

When monitoring is started, `CAMERA_AUTO_RECONNECT=true` makes the worker retry failed opens and frame reads using exponential backoff (`CAMERA_RECONNECT_DELAY`, capped at `CAMERA_MAX_RECONNECT_DELAY`). RTSP open/read timeouts use `CAMERA_OPEN_TIMEOUT` and `CAMERA_READ_TIMEOUT` in milliseconds. Stop monitoring interrupts the retry wait. Camera status reports `Reconnecting` along with the attempt count and remaining retry delay. If a sample fallback is active, the worker keeps probing the real RTSP source and returns to it when a frame is available.

The default model is `models/yolov8n.pt`. If absent, Ultralytics falls back to its pretrained `yolov8n.pt` (download may require internet access on first launch). Set `MODEL_PATH` to a local custom model to use it instead. Detector creation occurs once when monitoring starts, not once per frame. The worker uses CPU fallback through Ultralytics if CUDA is unavailable.

## Configuration

All values are read from environment variables / `.env`; see `.env.example`. Relevant settings include confidence/IoU thresholds, inference FPS, alert cooldown, zone mode, SQLite URL, and ntfy enable/topic. Set `ADMIN_TOKEN` to a strong secret before using administrative endpoints. RTSP secrets must never be committed or sent to the browser.

`RTSP_URL` may contain a complete RTSP URL. Alternatively, set `RTSP_USERNAME`, `RTSP_PASSWORD`, `RTSP_IP`, `RTSP_PORT`, `RTSP_CHANNEL`, and `RTSP_SUBTYPE`; the app builds a Dahua-style `/cam/realmonitor` URL and percent-encodes credentials. `RTSP_URL`, when nonempty, takes precedence over the component fields. Keep camera credentials in `.env` and do not commit them.

`config/zones.json` stores polygon vertices as normalized `[x,y]` values in `[0,1]`. Adjust the points to the Camera 14 view. The supplied polygon is an example overlay and must be calibrated against the actual scene. Zone changes can be sent to `POST /api/zones` with `{ "name":"Restricted Area", "mode":"crossing", "points":[[0.7,0.3],[0.98,0.3],[0.98,0.98],[0.7,0.98]] }`.

Modes: `crossing` alerts on an outside-to-inside transition; `intrusion` alerts on first entry into the zone; `approach` warns when a person's bottom-center anchor is within `APPROACH_DISTANCE` pixels of its boundary. Alerts use track IDs and cooldowns. Event evidence stores the annotated frame in `evidence/YYYY/MM/camera_14/`.

## API

- `GET /api/health`, `/api/cameras`, `/api/cameras/14/status`
- `GET /api/stream.mjpg` processed camera feed
- `GET /api/alerts`, `/api/alerts/{id}`
- `GET /api/analytics/summary`, `/api/analytics/daily`
- `GET /api/zones`
- `POST /api/cameras/14/test-connection` (admin token required)
- `POST /api/cameras/14/start`, `/api/cameras/14/stop`
- `POST /api/zones`, `POST /api/alerts/{id}/acknowledge`
- `GET /api/evidence/{relative_path}?token=ADMIN_TOKEN`
- `WS /ws/alerts`

Administrative POSTs require `X-Admin-Token: <ADMIN_TOKEN>`. For example:

```powershell
$headers = @{ 'X-Admin-Token' = 'your-local-admin-token' }
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/cameras/14/start -Headers $headers
```

For production, place the app behind HTTPS and authentication, restrict allowed origins, protect the evidence endpoint with a real user/session identity layer, and use PostgreSQL by setting `DATABASE_URL`. The default setup is a local development configuration; it does not implement user accounts/RBAC or TLS termination.

## ntfy

Set `NTFY_ENABLED=true` and a private `NTFY_TOPIC` in `.env`. Critical events are published asynchronously from the camera thread and do not block frame processing.

## Validation

Run `pytest` for available backend checks. Run `npm install` and `npm run build` in `frontend` to validate the dashboard bundle. Camera/detection integration requires a reachable configured CCTV/NVR RTSP URL or a local recorded person video. Camera addresses and credentials are kept out of the repository documentation.
