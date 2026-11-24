import pytest
import numpy as np
from datetime import datetime, timezone
from backend.movement_security.movement_evaluator import MovementSecurityEngine


@pytest.fixture
def movement_engine(tmp_path):
    config_file = tmp_path / "test_movement_rules.json"
    config_content = """{
        "enabled": true,
        "working_hours": {
            "enabled": true,
            "start": "08:00",
            "end": "18:00",
            "timezone": "UTC"
        },
        "alert_cooldown_seconds": 10,
        "min_frames_in_zone": 1,
        "zones": [
            {
                "zone_id": "restricted_furnace",
                "zone_name": "Furnace Core",
                "zone_type": "RESTRICTED",
                "polygon": [[100, 100], [300, 100], [300, 300], [100, 300]],
                "allowed_roles": ["operator"],
                "allowed_employees": ["dharshan"],
                "after_hours_restricted": true,
                "severity": "CRITICAL"
            },
            {
                "zone_id": "controlled_hallway",
                "zone_name": "Controlled Hallway",
                "zone_type": "CONTROLLED",
                "polygon": [[400, 100], [600, 100], [600, 300], [400, 300]],
                "allowed_roles": ["operator", "staff"],
                "allowed_employees": ["dharshan", "divya"],
                "after_hours_restricted": false,
                "severity": "HIGH"
            }
        ],
        "employee_roles": {
            "dharshan": "operator",
            "divya": "staff"
        }
    }"""
    config_file.write_text(config_content)
    engine = MovementSecurityEngine(config_path=str(config_file))
    return engine


def test_authorised_employee_in_zone(movement_engine):
    # Dharshan (authorized operator) inside Furnace Core
    # footpoint at (200, 200) -> inside polygon [[100,100], [300,100], [300,300], [100,300]]
    person = {
        "id": 1,
        "box": [180, 100, 220, 200], # bottom center footpoint = (200, 200)
        "name": "dharshan",
        "confidence": 0.88,
    }
    now_ts = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    dt_utc = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    events = movement_engine.evaluate_person(person, 1, "Camera 14", now_ts, dt_utc)
    assert len(events) == 0
    assert person["identity_status"] == "AUTHORISED"


def test_unknown_person_in_restricted_zone(movement_engine):
    # Unknown person inside Furnace Core
    person = {
        "id": 2,
        "box": [180, 100, 220, 200],
        "name": "Unknown",
        "confidence": 0.75,
    }
    now_ts = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    dt_utc = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    events = movement_engine.evaluate_person(person, 1, "Camera 14", now_ts, dt_utc)
    assert len(events) == 1
    assert events[0]["event_type"] == "UNKNOWN_PERSON_DETECTION"
    assert events[0]["zone_name"] == "Furnace Core"
    assert events[0]["severity"] == "CRITICAL"
    assert person["identity_status"] == "UNKNOWN"


def test_unauthorised_employee_role_violation(movement_engine):
    # Divya (staff) entering Furnace Core (requires operator)
    person = {
        "id": 3,
        "box": [180, 100, 220, 200],
        "name": "divya",
        "confidence": 0.85,
    }
    now_ts = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    dt_utc = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    events = movement_engine.evaluate_person(person, 1, "Camera 14", now_ts, dt_utc)
    assert len(events) == 1
    assert events[0]["event_type"] == "UNAUTHORISED_MOVEMENT"
    assert events[0]["severity"] == "CRITICAL"
    assert "divya is unauthorized" in events[0]["description"].lower()


def test_after_hours_movement_alert(movement_engine):
    # Dharshan (authorized) inside Furnace Core at 22:00 UTC (after hours)
    person = {
        "id": 1,
        "box": [180, 100, 220, 200],
        "name": "dharshan",
        "confidence": 0.90,
    }
    now_ts = datetime(2026, 11, 24, 22, 0, 0, tzinfo=timezone.utc).timestamp()
    dt_utc = datetime(2026, 11, 24, 22, 0, 0, tzinfo=timezone.utc)

    events = movement_engine.evaluate_person(person, 1, "Camera 14", now_ts, dt_utc)
    assert len(events) == 1
    assert events[0]["event_type"] == "AFTER_HOURS_MOVEMENT"
    assert events[0]["severity"] == "CRITICAL"


def test_alert_cooldown_deduplication(movement_engine):
    person = {
        "id": 4,
        "box": [180, 100, 220, 200],
        "name": "Unknown",
        "confidence": 0.70,
    }
    t0 = 1000.0
    dt0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    # First detection -> Alert generated
    e1 = movement_engine.evaluate_person(person, 1, "Camera 14", t0, dt0)
    assert len(e1) == 1

    # Second detection 3 seconds later (< 10s cooldown) -> Deduplicated / suppressed
    e2 = movement_engine.evaluate_person(person, 1, "Camera 14", t0 + 3.0, dt0)
    assert len(e2) == 0

    # Third detection 12 seconds later (> 10s cooldown) -> Alert generated
    e3 = movement_engine.evaluate_person(person, 1, "Camera 14", t0 + 12.0, dt0)
    assert len(e3) == 1


def test_summary_counts(movement_engine):
    people = [
        {"id": 1, "identity_status": "AUTHORISED"},
        {"id": 2, "identity_status": "UNKNOWN"},
        {"id": 3, "identity_status": "UNAUTHORISED"},
        {"id": 4, "identity_status": "AUTHORISED"},
    ]
    summary = movement_engine.get_summary_counts(people)
    assert summary["total_detected"] == 4
    assert summary["authorised_count"] == 2
    assert summary["unknown_count"] == 1
    assert summary["unauthorised_count"] == 1


def test_pending_face_identity_resolves_before_movement_alert(movement_engine):
    person = {
        "id": 5,
        "box": [180, 100, 220, 200],
        "name": None,
        "identity_state": "PENDING",
        "confidence": 0.9,
    }
    t0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    assert movement_engine.evaluate_person(
        person, 1, "Camera 14", t0.timestamp(), t0
    ) == []

    person.update(name="Divya", identity_state="IDENTIFIED")
    t1 = t0.replace(second=1)
    events = movement_engine.evaluate_person(
        person, 1, "Camera 14", t1.timestamp(), t1
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "UNAUTHORISED_MOVEMENT"
    assert events[0]["employee_name"] == "Divya"
    assert events[0]["employee_id"] == "divya"


def test_pending_face_identity_falls_back_to_unknown_after_grace(movement_engine):
    person = {
        "id": 6,
        "box": [180, 100, 220, 200],
        "name": None,
        "identity_state": "PENDING",
        "confidence": 0.9,
    }
    t0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

    assert movement_engine.evaluate_person(
        person, 1, "Camera 14", t0.timestamp(), t0
    ) == []

    t1 = t0.replace(second=3)
    events = movement_engine.evaluate_person(
        person, 1, "Camera 14", t1.timestamp(), t1
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "UNKNOWN_PERSON_DETECTION"
    assert events[0]["identity_status"] == "UNKNOWN"
