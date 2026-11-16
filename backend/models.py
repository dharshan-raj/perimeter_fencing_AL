from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
def now(): return datetime.now(timezone.utc)
class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    nvr_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))
    stream_status: Mapped[str] = mapped_column(String(30), default="Disconnected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    alerts: Mapped[list["Alert"]] = relationship(back_populates="camera")
class Alert(Base):
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
    camera: Mapped[Camera] = relationship(back_populates="alerts")
class DetectionLog(Base):
    __tablename__ = "detection_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    tracking_id: Mapped[str] = mapped_column(String(80), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    bounding_box: Mapped[str] = mapped_column(Text)
    zone_status: Mapped[str] = mapped_column(String(30))
    detection_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_level: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
