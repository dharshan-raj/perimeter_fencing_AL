# ============================================================
# FILE: shared/schemas.py
# PURPOSE: Pydantic request/response schemas for all FastAPI
#          API endpoints across all 3 use cases.
# USE CASE: All (Shared)
#
# SCHEMAS DEFINED:
#   ZonePayload              → POST /api/zones (Use Case 1)
#   HeadcountEventCreate     → POST /api/headcount/events (Use Case 2)
#   HeadcountEventResponse   → GET  /api/headcount/events response
#   HeadcountSummary         → GET  /api/headcount/live response
#   HeadcountReport          → GET  /api/headcount/report/daily response
#   EmployeeTimingRecord     → Employee timing records
#   EmployeeAttendanceSummary → Attendance summary per employee
#   MovementEventCreate      → POST /api/movement/events (Use Case 3)
#   MovementEventResponse    → GET  /api/movement/events response
#   MovementSummaryResponse  → GET  /api/movement/summary response
#
# DEBUG TIPS:
#   - 422 Unprocessable Entity from API?
#       → Pydantic validation failed. Check request body matches schema.
#       → Check required fields: camera_id, tracking_id, direction, event_key.
#   - Zone update rejected?
#       → ZonePayload.points must have >= 3 items (min_length=3).
#       → mode must be: "crossing" | "intrusion" | "approach"
#   - Timestamp serialization issues?
#       → All datetime fields are stored/returned as UTC ISO 8601 strings.
# ============================================================

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


# =========================================================
# USE CASE 1: PERIMETER ZONE
# =========================================================

class ZonePayload(BaseModel):
    """Request body for updating the perimeter zone polygon via POST /api/zones."""
    name: str = "Restricted Area"
    mode: Literal["crossing", "intrusion", "approach"] = "crossing"
    points: list[tuple[float, float]] = Field(min_length=3)


# =========================================================
# USE CASE 2: HEADCOUNT EVENTS
# =========================================================

class HeadcountEventCreate(BaseModel):
    """Request body for manually recording a gate crossing event."""
    camera_id: int = Field(gt=0)
    gate_name: str = Field(default="Plant Entrance Gate 3", min_length=1, max_length=100)
    tracking_id: str = Field(min_length=1, max_length=80)
    employee_name: str | None = Field(default=None, max_length=100)
    direction: Literal["IN", "OUT"]
    event_key: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    event_timestamp: datetime | None = None


class HeadcountEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    gate_name: str
    tracking_id: str
    employee_name: str | None = None
    direction: str
    event_key: str
    confidence: float | None
    event_timestamp: datetime


class EmployeeTimingRecord(BaseModel):
    id: int
    employee_name: str
    direction: str
    gate_name: str
    tracking_id: str
    event_timestamp: datetime


class EmployeeAttendanceSummary(BaseModel):
    employee_name: str
    first_entry: str | None = None
    last_exit: str | None = None
    last_direction: str | None = None
    status: str = "Unknown"   # "Inside" or "Outside"
    total_entries: int = 0
    total_exits: int = 0


class HeadcountSummary(BaseModel):
    gate_name: str
    total_in: int = 0
    total_out: int = 0
    opening_count: int = 0
    current_inside: int = 0


class HeadcountReport(BaseModel):
    gate_name: str
    report_date: str
    total_in: int = 0
    total_out: int = 0
    opening_count: int = 0
    closing_count: int = 0


# =========================================================
# USE CASE 3: MOVEMENT SECURITY EVENTS
# =========================================================

class MovementEventCreate(BaseModel):
    """Request body for manually recording a movement security event."""
    camera_id: int = Field(gt=0)
    tracking_id: str
    employee_id: str | None = None
    employee_name: str | None = None
    identity_status: Literal["AUTHORISED", "UNKNOWN", "UNAUTHORISED"]
    event_type: str
    zone_name: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    confidence: float | None = None
    snapshot_path: str | None = None
    description: str | None = None
    event_timestamp: datetime | None = None


class MovementEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    tracking_id: str
    employee_id: str | None = None
    employee_name: str | None = None
    identity_status: str
    event_type: str
    zone_name: str
    severity: str
    confidence: float | None = None
    snapshot_path: str | None = None
    description: str | None = None
    event_timestamp: datetime
    created_at: datetime


class MovementSummaryResponse(BaseModel):
    total_detected: int = 0
    authorised_count: int = 0
    unknown_count: int = 0
    unauthorised_count: int = 0
    today_violations: int = 0
    restricted_zones_active: int = 0
    last_updated: str
