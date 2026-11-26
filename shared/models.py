# ============================================================
# FILE: shared/models.py
# PURPOSE: SQLAlchemy ORM models: Camera, Alert, DetectionLog, SystemLog, HeadcountEvent, MovementEvent
# USE CASE: Shared Infrastructure (Database Models)
# DEBUG TIPS:
#   - Tables are auto-created on startup via Base.metadata.create_all(bind=engine)
# ============================================================


from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now():
    return datetime.now(timezone.utc)


# =========================================================
# CAMERA MODEL
# =========================================================

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    nvr_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))
    stream_status: Mapped[str] = mapped_column(
        String(30), default="Disconnected"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="camera"
    )

    # NEW: Headcount events associated with this camera
    headcount_events: Mapped[list["HeadcountEvent"]] = relationship(
        back_populates="camera"
    )

    # NEW: Movement security events associated with this camera
    movement_events: Mapped[list["MovementEvent"]] = relationship(
        back_populates="camera"
    )


# =========================================================
# ALERT MODEL - EXISTING PERIMETER SECURITY
# =========================================================

class Alert(Base):
    __tablename__ = "alerts"

    __table_args__ = (
        Index(
            "ix_alert_camera_timestamp",
            "camera_id",
            "event_timestamp"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id"), index=True
    )

    person_tracking_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)

    confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    zone_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    crossing_direction: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )

    evidence_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    alert_status: Mapped[str] = mapped_column(
        String(30), default="Open", index=True
    )

    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )

    camera: Mapped["Camera"] = relationship(
        back_populates="alerts"
    )


# =========================================================
# DETECTION LOG MODEL - EXISTING
# =========================================================

class DetectionLog(Base):
    __tablename__ = "detection_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id"), index=True
    )

    tracking_id: Mapped[str] = mapped_column(
        String(80), index=True
    )

    confidence: Mapped[float] = mapped_column(Float)

    bounding_box: Mapped[str] = mapped_column(Text)

    zone_status: Mapped[str] = mapped_column(String(30))

    detection_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )


# =========================================================
# SYSTEM LOG MODEL - EXISTING
# =========================================================

class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    log_level: Mapped[str] = mapped_column(String(20), index=True)

    message: Mapped[str] = mapped_column(Text)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )


# =========================================================
# HEADCOUNT EVENT MODEL - NEW
# PLANT ENTRANCE GATE 3
# =========================================================

class HeadcountEvent(Base):
    __tablename__ = "headcount_events"

    __table_args__ = (
        Index(
            "ix_headcount_gate_timestamp",
            "gate_name",
            "event_timestamp"
        ),
        Index(
            "ix_headcount_camera_timestamp",
            "camera_id",
            "event_timestamp"
        ),
        Index(
            "ix_headcount_direction_timestamp",
            "direction",
            "event_timestamp"
        ),
        UniqueConstraint(
            "event_key",
            name="uq_headcount_event_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Camera that recorded the crossing
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id"), index=True
    )

    # Example: Plant Entrance Gate 3
    gate_name: Mapped[str] = mapped_column(
        String(100), index=True
    )

    # ByteTrack person tracking ID
    tracking_id: Mapped[str] = mapped_column(
        String(80), index=True
    )

    # Name of recognized employee (e.g. 'Dharshan', 'Dinesh') or None
    employee_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    # IN or OUT
    direction: Mapped[str] = mapped_column(
        String(10), index=True
    )

    # Unique identifier for each crossing event.
    # Prevents the same event from being inserted twice.
    event_key: Mapped[str] = mapped_column(
        String(100), unique=True
    )

    # YOLO detection confidence
    confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # Time when the person crossed the counting line
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )

    # Relationship with Camera
    camera: Mapped["Camera"] = relationship(
        back_populates="headcount_events"
    )


# =========================================================
# NEW: UNAUTHORISED MOVEMENT EVENT MODEL
# =========================================================

class MovementEvent(Base):
    """
    Stores human movement security events:
    - Unknown person detection in controlled zones
    - Restricted area entry
    - Unauthorized role/employee movement
    - After-hours factory movement
    """
    __tablename__ = "movement_events"

    __table_args__ = (
        Index("ix_movement_camera_timestamp", "camera_id", "event_timestamp"),
        Index("ix_movement_zone_timestamp", "zone_name", "event_timestamp"),
        Index("ix_movement_type_timestamp", "event_type", "event_timestamp"),
        Index("ix_movement_employee_timestamp", "employee_name", "event_timestamp"),
        Index("ix_movement_identity_timestamp", "identity_status", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    tracking_id: Mapped[str] = mapped_column(String(80), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # AUTHORISED / UNKNOWN / UNAUTHORISED
    identity_status: Mapped[str] = mapped_column(String(30), index=True)

    # UNAUTHORISED_MOVEMENT / RESTRICTED_ZONE_ENTRY / AFTER_HOURS_MOVEMENT / UNKNOWN_PERSON_DETECTION
    event_type: Mapped[str] = mapped_column(String(80), index=True)

    zone_name: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)  # LOW / MEDIUM / HIGH / CRITICAL

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    camera: Mapped["Camera"] = relationship(back_populates="movement_events")


