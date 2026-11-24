
import asyncio
import logging

from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone, date

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Header,
    WebSocket,
    WebSocketDisconnect,
    Query,
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .config import settings
from .database import Base, engine, get_db, SessionLocal
from . import models
from .schemas import HeadcountEventCreate
from .camera.camera_manager import camera_manager
from .detection.zone_manager import ZoneManager
from .services.websocket_manager import manager
from .services.notification_service import send_ntfy


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

logger = logging.getLogger(__name__)

loop = None


# =========================================================
# WEBSOCKET + NOTIFICATION PUBLISHING
# =========================================================

async def publish(payload, notify=False):
    await manager.broadcast(payload)

    if notify and payload.get("severity") == "CRITICAL":
        await send_ntfy(payload)


def publish_from_thread(payload, notify=False):
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            publish(payload, notify),
            loop
        )


# =========================================================
# APPLICATION LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app):
    global loop

    loop = asyncio.get_running_loop()

    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Ensure existing sqlite databases have the employee_name column
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(headcount_events)"))
            cols = [r[1] for r in res.fetchall()]
            if "employee_name" not in cols and "id" in cols:
                conn.execute(text("ALTER TABLE headcount_events ADD COLUMN employee_name VARCHAR(100)"))
                logger.info("Migrated headcount_events: added employee_name column")
    except Exception as exc:
        logger.warning("Could not auto-migrate headcount_events table: %s", exc)

    db = SessionLocal()

    try:
        # Register existing perimeter camera
        camera = db.query(models.Camera).filter_by(
            camera_name=settings.camera_name
        ).first()

        if not camera:
            db.add(
                models.Camera(
                    camera_name=settings.camera_name,
                    nvr_name=settings.nvr_name,
                    location=settings.camera_location
                )
            )
            db.commit()

    finally:
        db.close()

    if settings.camera_auto_start and settings.source:
        logger.info(
            "Starting perimeter camera worker automatically"
        )
        camera_manager.start()

    yield

    camera_manager.stop()


# =========================================================
# FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="IT Furnace Perimeter & Headcount Monitoring",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# ADMIN AUTHENTICATION
# =========================================================

def admin(
    x_admin_token: str | None = Header(default=None)
):
    if x_admin_token != settings.admin_token:
        raise HTTPException(
            status_code=401,
            detail="Valid X-Admin-Token required"
        )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "camera_status": camera_manager.status,
        "modules": {
            "perimeter_monitoring": "enabled",
            "headcount_monitoring": "enabled"
        }
    }


# =========================================================
# CAMERA MANAGEMENT - EXISTING
# =========================================================

@app.get("/api/cameras")
def cameras(db: Session = Depends(get_db)):

    return [
        {
            "id": c.id,
            "camera_name": c.camera_name,
            "nvr_name": c.nvr_name,
            "location": c.location,
            "stream_status": (
                camera_manager.status
                if c.camera_name == settings.camera_name
                else c.stream_status
            ),
            "last_frame": (
                camera_manager.last_frame is not None
                if c.camera_name == settings.camera_name
                else False
            )
        }
        for c in db.query(models.Camera).all()
    ]


@app.get("/api/cameras/14/status")
def camera_status():

    return {
        "camera_name": settings.camera_name,
        "location": settings.camera_location,
        "source_type": settings.source_kind,
        "active_source": camera_manager.active_source,
        "stream_status": camera_manager.status,
        "video_status": camera_manager.video_status,
        "last_frame_timestamp": camera_manager.last_frame_timestamp,
        "processing": bool(
            camera_manager.thread
            and camera_manager.thread.is_alive()
        ),
        "dual_gate_cameras": bool(
            settings.dual_gate_cameras
            and camera_manager.in_thread
            and camera_manager.in_thread.is_alive()
        ),
        "auto_start": settings.camera_auto_start,
        "auto_reconnect": settings.camera_auto_reconnect,
        "reconnect_attempt": (
            camera_manager.stream.retry_attempt
            if camera_manager.stream
            else camera_manager.reconnect_attempt
        ),
        "retry_in_seconds": (
            camera_manager.stream.retry_wait_seconds
            if camera_manager.stream
            else 0
        ),
        "source_configured": bool(settings.source)
    }


@app.post(
    "/api/cameras/14/test-connection",
    dependencies=[Depends(admin)]
)
def test_camera_connection():

    result = camera_manager.test_connection()

    result.update({
        "camera_name": settings.camera_name,
        "location": settings.camera_location,
        "configured_source_type": settings.source_kind
    })

    return result


# =========================================================
# EXISTING PERIMETER LIVE VIDEO STREAM
# =========================================================

@app.get("/api/stream.mjpg")
def stream():

    def frames():
        import cv2
        import time

        while True:

            frame = camera_manager.last_frame

            if frame is not None:

                image = frame.copy()

                camera_manager.zone.annotate(image)
                if camera_manager.in_thread and camera_manager.in_thread.is_alive():
                    camera_manager.headcount.annotate_out(image)
                else:
                    camera_manager.headcount.annotate(image)

                for person in camera_manager.people:

                    x1, y1, x2, y2 = person["box"]

                    cv2.rectangle(
                        image,
                        (x1, y1),
                        (x2, y2),
                        (54, 210, 185),
                        2
                    )

                    cv2.putText(
                        image,
                        f"{person.get('name') or ('ID ' + str(person['id']))} {person['confidence']:.2f}",
                        (x1, max(18, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (54, 210, 185),
                        2
                    )

                # Fast JPEG compression (quality 70) for low-latency browser streaming
                ok, data = cv2.imencode(
                    ".jpg",
                    image,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 70]
                )

                if ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + data.tobytes()
                        + b"\r\n"
                    )

            time.sleep(0.04)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/stream_in.mjpg")
def stream_in():
    """Live MJPEG stream for Gate 3 IN Camera (Channel 1)."""
    def frames():
        import cv2
        import time

        while True:
            frame = camera_manager.last_in_frame
            if frame is not None:
                image = frame.copy()
                camera_manager.headcount.annotate_in(image)
                for person in camera_manager.in_people:
                    x1, y1, x2, y2 = person["box"]
                    cv2.rectangle(image, (x1, y1), (x2, y2), (50, 220, 100), 2)
                    cv2.putText(
                        image,
                        f"{person.get('name') or ('ID ' + str(person['id']))} {person['confidence']:.2f}",
                        (x1, max(18, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (50, 220, 100),
                        2
                    )
                ok, data = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + data.tobytes()
                        + b"\r\n"
                    )
            time.sleep(0.04)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# =========================================================
# EXISTING PERIMETER ALERTS
# =========================================================

@app.get("/api/alerts")
def alerts(
    limit: int = Query(100, ge=1, le=500),
    severity: str | None = None,
    event_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db)
):

    q = db.query(models.Alert).order_by(
        models.Alert.event_timestamp.desc()
    )

    if severity:
        q = q.filter(
            models.Alert.severity == severity.upper()
        )

    if event_type:
        q = q.filter(
            models.Alert.event_type == event_type
        )

    if status:
        q = q.filter(
            models.Alert.alert_status == status
        )

    return [
        {
            "id": a.id,
            "camera_name": a.camera.camera_name,
            "nvr_name": a.camera.nvr_name,
            "location": a.camera.location,
            "person_tracking_id": a.person_tracking_id,
            "event_type": a.event_type,
            "severity": a.severity,
            "confidence": a.confidence,
            "zone_name": a.zone_name,
            "crossing_direction": a.crossing_direction,
            "evidence_path": None,
            "alert_status": a.alert_status,
            "event_timestamp": a.event_timestamp.isoformat()
        }
        for a in q.limit(limit).all()
    ]


@app.get("/api/alerts/{alert_id}")
def alert_detail(
    alert_id: int,
    db: Session = Depends(get_db)
):

    a = db.get(models.Alert, alert_id)

    if not a:
        raise HTTPException(404, "Alert not found")

    return {
        "id": a.id,
        "person_tracking_id": a.person_tracking_id,
        "event_type": a.event_type,
        "severity": a.severity,
        "confidence": a.confidence,
        "crossing_direction": a.crossing_direction,
        "evidence_path": a.evidence_path,
        "alert_status": a.alert_status,
        "event_timestamp": a.event_timestamp.isoformat()
    }


@app.post(
    "/api/alerts/{alert_id}/acknowledge",
    dependencies=[Depends(admin)]
)
def acknowledge(
    alert_id: int,
    db: Session = Depends(get_db)
):

    a = db.get(models.Alert, alert_id)

    if not a:
        raise HTTPException(404, "Alert not found")

    a.alert_status = "Acknowledged"
    db.commit()

    return {
        "id": a.id,
        "alert_status": a.alert_status
    }


# =========================================================
# EXISTING PERIMETER ANALYTICS
# =========================================================

@app.get("/api/analytics/summary")
def summary(db: Session = Depends(get_db)):

    total = db.query(models.Alert).count()

    critical = db.query(models.Alert).filter_by(
        severity="CRITICAL"
    ).count()

    active = db.query(models.Alert).filter_by(
        alert_status="Open"
    ).count()

    return {
        "total_people_detected": camera_manager.total_people,
        "total_crossings": camera_manager.crossings,
        "total_intrusion_alerts": critical,
        "active_incidents": active,
        "camera_status": camera_manager.status,
        "total_alerts": total
    }


@app.get("/api/analytics/daily")
def daily(db: Session = Depends(get_db)):

    rows = db.query(
        func.date(models.Alert.event_timestamp),
        func.count(models.Alert.id)
    ).group_by(
        func.date(models.Alert.event_timestamp)
    ).order_by(
        func.date(models.Alert.event_timestamp)
    ).all()

    hours = db.query(
        func.strftime(
            '%H',
            models.Alert.event_timestamp
        ),
        func.count(models.Alert.id)
    ).group_by(
        func.strftime(
            '%H',
            models.Alert.event_timestamp
        )
    ).all()

    kinds = db.query(
        models.Alert.event_type,
        func.count(models.Alert.id)
    ).group_by(
        models.Alert.event_type
    ).all()

    return {
        "daily": [
            {"date": str(d), "count": c}
            for d, c in rows
        ],
        "hourly": [
            {"hour": h, "count": c}
            for h, c in hours
        ],
        "event_types": [
            {"name": n, "count": c}
            for n, c in kinds
        ]
    }


# =========================================================
# EXISTING ZONE MANAGEMENT
# =========================================================

@app.get("/api/zones")
def get_zone():
    return camera_manager.zone.zone


@app.post(
    "/api/zones",
    dependencies=[Depends(admin)]
)
def set_zone(payload: dict):

    try:
        return camera_manager.zone.update(payload)

    except ValueError as e:
        raise HTTPException(422, str(e))


# =========================================================
# EXISTING CAMERA START / STOP
# =========================================================

@app.post(
    "/api/cameras/14/start",
    dependencies=[Depends(admin)]
)
def start():

    camera_manager.start()

    return {"status": "starting"}


@app.post(
    "/api/cameras/14/stop",
    dependencies=[Depends(admin)]
)
def stop():

    camera_manager.stop()

    return {"status": "stopping"}


# =========================================================
# EVIDENCE IMAGE
# =========================================================

@app.get("/api/evidence/{filename:path}")
def evidence(
    filename: str,
    token: str = Query(...)
):

    if token != settings.admin_token:
        raise HTTPException(
            401,
            "Authentication required"
        )

    root = Path(settings.evidence_dir).resolve()

    target = (root / filename).resolve()

    if root not in target.parents or not target.is_file():
        raise HTTPException(
            404,
            "Evidence not found"
        )

    return FileResponse(
        target,
        media_type="image/jpeg"
    )


# =========================================================
# NEW USE CASE: GATE 3 HEADCOUNT MONITORING
# =========================================================

DEFAULT_GATE_NAME = "Plant Entrance Gate 3"


# ---------------------------------------------------------
# REGISTER ENTRY / EXIT EVENT
# ---------------------------------------------------------

@app.post(
    "/api/headcount/events",
    dependencies=[Depends(admin)]
)
def create_headcount_event(
    payload: HeadcountEventCreate,
    db: Session = Depends(get_db)
):

    # Check whether the camera exists
    camera = db.get(
        models.Camera,
        payload.camera_id
    )

    if not camera:
        raise HTTPException(
            status_code=404,
            detail="Headcount camera not found"
        )

    # Prevent duplicate event insertion
    existing = db.query(
        models.HeadcountEvent
    ).filter_by(
        event_key=payload.event_key
    ).first()

    if existing:
        return {
            "status": "duplicate",
            "message": "This crossing event was already recorded",
            "event_id": existing.id
        }

    event = models.HeadcountEvent(
        camera_id=payload.camera_id,
        gate_name=payload.gate_name,
        tracking_id=payload.tracking_id,
        employee_name=payload.employee_name,
        direction=payload.direction,
        event_key=payload.event_key,
        confidence=payload.confidence,
        event_timestamp=(
            payload.event_timestamp
            or datetime.now(timezone.utc)
        )
    )

    try:
        db.add(event)
        db.commit()
        db.refresh(event)

    except IntegrityError:
        db.rollback()

        existing = db.query(
            models.HeadcountEvent
        ).filter_by(
            event_key=payload.event_key
        ).first()

        return {
            "status": "duplicate",
            "message": "Crossing event already exists",
            "event_id": existing.id if existing else None
        }

    logger.info(
        "Headcount event recorded: Gate=%s Direction=%s TrackingID=%s",
        event.gate_name,
        event.direction,
        event.tracking_id
    )

    return {
        "status": "success",
        "message": "Headcount event recorded",
        "event_id": event.id,
        "gate_name": event.gate_name,
        "direction": event.direction,
        "event_timestamp": event.event_timestamp.isoformat()
    }


# ---------------------------------------------------------
# LIVE HEADCOUNT SUMMARY
# ---------------------------------------------------------

@app.get("/api/headcount/live")
def live_headcount(
    gate_name: str = Query(DEFAULT_GATE_NAME),
    opening_count: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):

    total_in = db.query(
        func.count(models.HeadcountEvent.id)
    ).filter(
        models.HeadcountEvent.gate_name == gate_name,
        models.HeadcountEvent.direction == "IN"
    ).scalar() or 0

    total_out = db.query(
        func.count(models.HeadcountEvent.id)
    ).filter(
        models.HeadcountEvent.gate_name == gate_name,
        models.HeadcountEvent.direction == "OUT"
    ).scalar() or 0

    current_inside = max(
        0,
        opening_count + total_in - total_out
    )

    return {
        "gate_name": gate_name,
        "total_in": total_in,
        "total_out": total_out,
        "opening_count": opening_count,
        "current_inside": current_inside,
        "last_updated": datetime.now(
            timezone.utc
        ).isoformat()
    }


# ---------------------------------------------------------
# HEADCOUNT EVENT HISTORY
# ---------------------------------------------------------

@app.get("/api/headcount/events")
def get_headcount_events(
    gate_name: str = Query(DEFAULT_GATE_NAME),
    direction: str | None = Query(
        None,
        pattern="^(IN|OUT)$"
    ),
    employee_name: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):

    query = db.query(
        models.HeadcountEvent
    ).filter(
        models.HeadcountEvent.gate_name == gate_name
    )

    if direction:
        query = query.filter(
            models.HeadcountEvent.direction == direction
        )

    if employee_name:
        query = query.filter(
            models.HeadcountEvent.employee_name.ilike(f"%{employee_name}%")
        )

    events = query.order_by(
        models.HeadcountEvent.event_timestamp.desc()
    ).limit(limit).all()

    return [
        {
            "id": event.id,
            "camera_id": event.camera_id,
            "gate_name": event.gate_name,
            "tracking_id": event.tracking_id,
            "employee_name": event.employee_name,
            "direction": event.direction,
            "confidence": event.confidence,
            "event_timestamp": event.event_timestamp.isoformat()
        }
        for event in events
    ]


# ---------------------------------------------------------
# EMPLOYEE ENTRY & EXIT TIMINGS (DETAILED LOG)
# ---------------------------------------------------------

@app.get("/api/headcount/employee-timings")
def get_employee_timings(
    employee_name: str | None = Query(None),
    direction: str | None = Query(None, pattern="^(IN|OUT)$"),
    target_date: date | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Returns entry and exit timing records for recognized employees.
    """
    query = db.query(models.HeadcountEvent).filter(
        models.HeadcountEvent.employee_name.isnot(None)
    )

    if employee_name:
        query = query.filter(
            models.HeadcountEvent.employee_name.ilike(f"%{employee_name}%")
        )

    if direction:
        query = query.filter(
            models.HeadcountEvent.direction == direction
        )

    if target_date:
        query = query.filter(
            func.date(models.HeadcountEvent.event_timestamp) == target_date.isoformat()
        )

    events = query.order_by(
        models.HeadcountEvent.event_timestamp.desc()
    ).limit(limit).all()

    return [
        {
            "id": event.id,
            "employee_name": event.employee_name,
            "direction": event.direction,
            "gate_name": event.gate_name,
            "tracking_id": event.tracking_id,
            "confidence": event.confidence,
            "event_timestamp": event.event_timestamp.isoformat()
        }
        for event in events
    ]


# ---------------------------------------------------------
# EMPLOYEE ATTENDANCE SUMMARY (TODAY)
# ---------------------------------------------------------

@app.get("/api/headcount/attendance/today")
def get_today_attendance(
    target_date: date = Query(default_factory=date.today),
    db: Session = Depends(get_db)
):
    """
    Computes first entry time, last exit time, and inside/outside
    status for each recognized employee on the given date.
    """
    date_str = target_date.isoformat()

    events = db.query(models.HeadcountEvent).filter(
        models.HeadcountEvent.employee_name.isnot(None),
        func.date(models.HeadcountEvent.event_timestamp) == date_str
    ).order_by(
        models.HeadcountEvent.event_timestamp.asc()
    ).all()

    summary: dict[str, dict] = {}

    for evt in events:
        emp = evt.employee_name
        if emp not in summary:
            summary[emp] = {
                "employee_name": emp,
                "first_entry": None,
                "last_exit": None,
                "last_direction": None,
                "status": "Outside",
                "total_entries": 0,
                "total_exits": 0,
                "latest_time": None
            }

        rec = summary[emp]
        ts_iso = evt.event_timestamp.isoformat()

        if evt.direction == "IN":
            rec["total_entries"] += 1
            if rec["first_entry"] is None:
                rec["first_entry"] = ts_iso
            rec["status"] = "Inside"
        elif evt.direction == "OUT":
            rec["total_exits"] += 1
            rec["last_exit"] = ts_iso
            rec["status"] = "Outside"

        rec["last_direction"] = evt.direction
        rec["latest_time"] = ts_iso

    return list(summary.values())


# ---------------------------------------------------------
# DAILY HEADCOUNT REPORT
# ---------------------------------------------------------

@app.get("/api/headcount/reports/daily")
def daily_headcount_report(
    report_date: date = Query(
        default_factory=date.today
    ),
    gate_name: str = Query(DEFAULT_GATE_NAME),
    opening_count: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):

    date_value = report_date.isoformat()

    total_in = db.query(
        func.count(models.HeadcountEvent.id)
    ).filter(
        models.HeadcountEvent.gate_name == gate_name,
        models.HeadcountEvent.direction == "IN",
        func.date(
            models.HeadcountEvent.event_timestamp
        ) == date_value
    ).scalar() or 0

    total_out = db.query(
        func.count(models.HeadcountEvent.id)
    ).filter(
        models.HeadcountEvent.gate_name == gate_name,
        models.HeadcountEvent.direction == "OUT",
        func.date(
            models.HeadcountEvent.event_timestamp
        ) == date_value
    ).scalar() or 0

    return {
        "gate_name": gate_name,
        "report_date": date_value,
        "total_in": total_in,
        "total_out": total_out,
        "opening_count": opening_count,
        "closing_count": opening_count + total_in - total_out
    }


# ---------------------------------------------------------
# MONTHLY HEADCOUNT REPORT
# ---------------------------------------------------------

@app.get("/api/headcount/reports/monthly")
def monthly_headcount_report(
    year: int = Query(
        default_factory=lambda: date.today().year,
        ge=2000,
        le=2100
    ),
    month: int = Query(
        default_factory=lambda: date.today().month,
        ge=1,
        le=12
    ),
    gate_name: str = Query(DEFAULT_GATE_NAME),
    db: Session = Depends(get_db)
):

    month_value = f"{year:04d}-{month:02d}"

    rows = db.query(
        func.date(models.HeadcountEvent.event_timestamp),
        models.HeadcountEvent.direction,
        func.count(models.HeadcountEvent.id)
    ).filter(
        models.HeadcountEvent.gate_name == gate_name,
        func.strftime(
            "%Y-%m",
            models.HeadcountEvent.event_timestamp
        ) == month_value
    ).group_by(
        func.date(models.HeadcountEvent.event_timestamp),
        models.HeadcountEvent.direction
    ).order_by(
        func.date(models.HeadcountEvent.event_timestamp)
    ).all()

    daily_data = {}

    for event_date, direction, count in rows:

        if event_date not in daily_data:
            daily_data[event_date] = {
                "date": str(event_date),
                "total_in": 0,
                "total_out": 0
            }

        if direction == "IN":
            daily_data[event_date]["total_in"] = count

        elif direction == "OUT":
            daily_data[event_date]["total_out"] = count

    total_in = sum(
        item["total_in"]
        for item in daily_data.values()
    )

    total_out = sum(
        item["total_out"]
        for item in daily_data.values()
    )

    return {
        "gate_name": gate_name,
        "month": month_value,
        "total_in": total_in,
        "total_out": total_out,
        "daily_records": list(daily_data.values())
    }


# =========================================================
# EXISTING WEBSOCKET ALERT CONNECTION
# =========================================================

@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):

    await manager.connect(ws)

    try:
        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(ws)
