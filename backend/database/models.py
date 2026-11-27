# ============================================================
# FILE: shared/models.py
# PURPOSE: SQLAlchemy ORM models for all database tables used
#          across all 3 use cases.
# USE CASE: All (Shared)
#
# TABLES DEFINED:
#   cameras          → Registered camera devices
#   alerts           → Perimeter intrusion/crossing alerts (Use Case 1)
#   detection_logs   → Per-frame detection records (all use cases)
#   system_logs      → Application system events and errors
#   headcount_events → Gate entry/exit crossing events (Use Case 2)
#   movement_events  → Unauthorized movement alerts (Use Case 3)
#
# DEBUG TIPS:
#   - Table missing / "no such table"?
#       → Run: Base.metadata.create_all(engine) on startup (done in main.py).
#   - "UNIQUE constraint failed: headcount_events.event_key"?
#       → This is expected — prevents duplicate crossings. event_key must be unique.
#   - Column missing in existing DB?
#       → main.py runs ALTER TABLE for known migrations (e.g., employee_name column).
#       → For new columns: add here, then run ALTER TABLE or delete and recreate the DB.
#   - Relationship lazy loading error?
#       → expire_on_commit=False in SessionLocal helps.
#       → Use db.refresh(obj) after commit to access related objects.
#
# DEPENDENCIES:
#   - shared/database.py  → Base (DeclarativeBase)
# ============================================================

from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.database import Base


def now():
    """Current UTC datetime — used as default for timestamp columns."""
    return datetime.now(timezone.utc)


# =========================================================
# CAMERA
# =========================================================

class Camera(Base):
    """Registered camera devices. One record per physical camera."""
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    nvr_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))
    stream_status: Mapped[str] = mapped_column(String(30), default="Disconnected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    alerts: Mapped[list["Alert"]] = relationship(back_populates="camera")
    headcount_events: Mapped[list["HeadcountEvent"]] = relationship(back_populates="camera")
    movement_events: Mapped[list["MovementEvent"]] = relationship(back_populates="camera")


# =========================================================
# ALERT — Use Case 1: Perimeter Fencing
# =========================================================

class Alert(Base):
    """Perimeter intrusion / boundary crossing alert records."""
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_camera_timestamp", "camera_id", "event_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    person_tracking_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    crossing_direction: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    alert_status: Mapped[str] = mapped_column(String(30), default="Open", index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    camera: Mapped["Camera"] = relationship(back_populates="alerts")


# =========================================================
# DETECTION LOG
# =========================================================

class DetectionLog(Base):
    """Per-frame detection record for every tracked person."""
    __tablename__ = "detection_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    tracking_id: Mapped[str] = mapped_column(String(80), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    bounding_box: Mapped[str] = mapped_column(Text)
    zone_status: Mapped[str] = mapped_column(String(30))
    detection_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# =========================================================
# SYSTEM LOG
# =========================================================

class SystemLog(Base):
    """Application-level system events, errors, and status messages."""
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_level: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# =========================================================
# HEADCOUNT EVENT — Use Case 2: Entry/Exit Headcount
# =========================================================

class HeadcountEvent(Base):
    """Gate entry/exit crossing events at Plant Entrance Gate 3."""
    __tablename__ = "headcount_events"
    __table_args__ = (
        Index("ix_headcount_gate_timestamp", "gate_name", "event_timestamp"),
        Index("ix_headcount_camera_timestamp", "camera_id", "event_timestamp"),
        Index("ix_headcount_direction_timestamp", "direction", "event_timestamp"),
        UniqueConstraint("event_key", name="uq_headcount_event_key"),
        # DEBUG: UniqueConstraint on event_key prevents duplicate crossings.
        # If INSERT fails with UNIQUE constraint: event already recorded — safe to ignore.
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    gate_name: Mapped[str] = mapped_column(String(100), index=True)
    tracking_id: Mapped[str] = mapped_column(String(80), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(10), index=True)         # "IN" or "OUT"
    event_key: Mapped[str] = mapped_column(String(100), unique=True)       # Dedup key
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    camera: Mapped["Camera"] = relationship(back_populates="headcount_events")


# =========================================================
# MOVEMENT EVENT — Use Case 3: Movement Security
# =========================================================

class MovementEvent(Base):
    """
    Unauthorized movement security events:
    - UNKNOWN_PERSON_DETECTION
    - UNAUTHORISED_MOVEMENT
    - AFTER_HOURS_MOVEMENT
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
    identity_status: Mapped[str] = mapped_column(String(30), index=True)   # AUTHORISED / UNKNOWN / UNAUTHORISED
    event_type: Mapped[str] = mapped_column(String(80), index=True)         # Violation type
    zone_name: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)           # LOW / MEDIUM / HIGH / CRITICAL
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    camera: Mapped["Camera"] = relationship(back_populates="movement_events")
