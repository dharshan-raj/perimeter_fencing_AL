"""
Tests for Pose-based Leg Intrusion + Separate Face Authorization rules.
Validates all 5 required behaviors:
  1. Authorized employee walks outside zone             -> No alert
  2. Authorized employee's leg enters restricted zone   -> Leg Intrusion alert (NOT bypassed)
  3. Unknown person's leg enters restricted zone        -> Leg Intrusion - Unauthorised Person alert
  4. Unknown person remains outside zone                -> No perimeter alert
  5. Person body/foot enters restricted zone            -> Intrusion alert
"""

from backend.use_cases.perimeter.zone_manager import ZoneManager
from backend.use_cases.perimeter.intrusion_detector import IntrusionDetector

FRAME_SHAPE = (720, 1280, 3)


def _make_detector(tmp_path, mode="intrusion"):
    zm = ZoneManager(path=str(tmp_path / "zones.json"))
    zm.update({
        "name": "Restricted Area",
        "mode": mode,
        "allowed_employees": ["dharshan"],
        "points": [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9], [0.5, 0.9]],  # x: 640..1152, y: 360..648
    })
    return IntrusionDetector(zm, mode=mode)


def test_authorized_employee_outside_zone_no_alert(tmp_path):
    det = _make_detector(tmp_path)
    person = {
        "id": 1,
        "name": "dharshan",
        "point": [300, 500],
        "leg_keypoints": {
            "left_knee": [290, 420, 0.9],
            "left_ankle": [295, 495, 0.9],
            "right_knee": [310, 420, 0.9],
            "right_ankle": [315, 495, 0.9],
        },
    }
    res = det.evaluate(person, FRAME_SHAPE, cooldown=30)
    assert res["inside"] is False
    assert res["leg_inside"] is False
    assert res["authorised"] is True
    assert res["event"] is None


def test_authorized_employee_leg_enters_zone_triggers_leg_intrusion(tmp_path):
    """Important: recognized employee MUST NOT bypass restricted-zone leg violation."""
    det = _make_detector(tmp_path)
    person = {
        "id": 2,
        "name": "dharshan",
        "point": [620, 500],  # torso/center still outside (x=620 < 640)
        "leg_keypoints": {
            "left_knee": [610, 440, 0.9],
            "left_ankle": [615, 500, 0.9],
            "right_knee": [650, 440, 0.85],   # inside zone (x=650 >= 640, y=440 in 360..648)
            "right_ankle": [670, 510, 0.88],  # inside zone
        },
    }
    res = det.evaluate(person, FRAME_SHAPE, cooldown=30)
    assert res["inside"] is True
    assert res["leg_inside"] is True
    assert set(res["leg_parts_inside"]) == {"right_knee", "right_ankle"}
    assert res["authorised"] is True
    assert res["employee_name"] == "dharshan"
    assert res["event"] == "Leg Intrusion"


def test_unknown_person_leg_enters_zone_triggers_intrusion_and_unauthorised(tmp_path):
    det = _make_detector(tmp_path)
    person = {
        "id": 3,
        "name": "Unknown",
        "point": [620, 500],
        "leg_keypoints": {
            "left_ankle": [660, 500, 0.82],  # inside zone
        },
    }
    res = det.evaluate(person, FRAME_SHAPE, cooldown=30)
    assert res["inside"] is True
    assert res["leg_inside"] is True
    assert res["authorised"] is False
    assert res["event"] == "Leg Intrusion - Unauthorised Person"


def test_unknown_person_outside_zone_no_perimeter_alert(tmp_path):
    det = _make_detector(tmp_path)
    person = {
        "id": 4,
        "name": None,
        "point": [200, 200],
        "leg_keypoints": {
            "left_ankle": [195, 200, 0.9],
            "right_ankle": [205, 200, 0.9],
        },
    }
    res = det.evaluate(person, FRAME_SHAPE, cooldown=30)
    assert res["inside"] is False
    assert res["leg_inside"] is False
    assert res["authorised"] is False
    assert res["event"] is None


def test_person_enters_zone_without_pose_keypoints_fallback(tmp_path):
    """Fallback to bottom-center point when pose keypoints are unavailable."""
    det = _make_detector(tmp_path, mode="intrusion")
    person = {
        "id": 5,
        "name": "dinesh",
        "point": [750, 500],  # inside zone
        "leg_keypoints": {},
    }
    res = det.evaluate(person, FRAME_SHAPE, cooldown=30)
    assert res["inside"] is True
    assert res["leg_inside"] is False
    assert res["authorised"] is True
    assert res["event"] == "Restricted Zone Intrusion"
