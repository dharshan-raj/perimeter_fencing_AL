
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


# =========================================================
# EXISTING: PERIMETER ZONE SCHEMA
# =========================================================

class ZonePayload(BaseModel):
    name: str = "Restricted Area"

    mode: Literal["crossing", "intrusion", "approach"] = "crossing"

    points: list[tuple[float, float]] = Field(min_length=3)


# =========================================================
# NEW: HEADCOUNT EVENT SCHEMA
# =========================================================

class HeadcountEventCreate(BaseModel):
    camera_id: int = Field(gt=0)

    gate_name: str = Field(
        default="Plant Entrance Gate 3",
        min_length=1,
        max_length=100
    )

    tracking_id: str = Field(
        min_length=1,
        max_length=80
    )

    employee_name: str | None = Field(
        default=None,
        max_length=100
    )

    direction: Literal["IN", "OUT"]

    event_key: str = Field(
        min_length=1,
        max_length=100
    )

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0
    )

    event_timestamp: datetime | None = None


# =========================================================
# NEW: HEADCOUNT EVENT RESPONSE
# =========================================================

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


# =========================================================
# NEW: EMPLOYEE TIMING & ATTENDANCE SCHEMAS
# =========================================================

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
    status: str = "Unknown"  # "Inside" or "Outside"
    total_entries: int = 0
    total_exits: int = 0


# =========================================================
# NEW: LIVE HEADCOUNT RESPONSE
# =========================================================

class HeadcountSummary(BaseModel):
    gate_name: str

    total_in: int = 0

    total_out: int = 0

    opening_count: int = 0

    current_inside: int = 0


# =========================================================
# NEW: HEADCOUNT REPORT SCHEMA
# =========================================================

class HeadcountReport(BaseModel):
    gate_name: str

    report_date: str

    total_in: int = 0

    total_out: int = 0

    opening_count: int = 0

    closing_count: int = 0
