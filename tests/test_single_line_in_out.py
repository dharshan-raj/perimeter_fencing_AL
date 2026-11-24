import pytest
from backend.headcount.headcount_manager import HeadcountManager

def test_headcount_manager_single_line():
    manager = HeadcountManager(
        gate_name="Gate 3",
        two_lines=False,
        line_start=(100, 200),
        line_end=(500, 200),
        entry_direction="A_TO_B",
        confirmation_frames=1,
        cooldown=0.0,
    )
    frame_shape = (720, 1280, 3)

    # 1. Person 10 attempts to EXIT without entering (moves from y=250 to y=150)
    manager.process([{"id": 10, "name": "dharshan", "box": [200, 230, 220, 270], "confidence": 0.9}], frame_shape)
    events_unauth = manager.process([{"id": 10, "name": "dharshan", "box": [200, 130, 220, 170], "confidence": 0.9}], frame_shape)
    # Must NOT count OUT because they never entered!
    assert len(events_unauth) == 0
    assert manager.get_counts()["total_out"] == 0

    # 2. Person 10 now ENTERS (moves from y=150 to y=250)
    manager.process([{"id": 10, "name": "dharshan", "box": [200, 130, 220, 170], "confidence": 0.9}], frame_shape)
    events_in = manager.process([{"id": 10, "name": "dharshan", "box": [200, 230, 220, 270], "confidence": 0.9}], frame_shape)
    assert any(e["direction"] == "IN" and e["employee_name"] == "dharshan" for e in events_in)
    counts = manager.get_counts()
    assert counts["total_in"] == 1
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 1
    assert "dharshan" in manager._inside_employees

    # 3. Person 10 now EXITS (moves from y=250 to y=150)
    manager.process([{"id": 10, "name": "dharshan", "box": [200, 230, 220, 270], "confidence": 0.9}], frame_shape)
    events_out = manager.process([{"id": 10, "name": "dharshan", "box": [200, 130, 220, 170], "confidence": 0.9}], frame_shape)
    assert any(e["direction"] == "OUT" and e["employee_name"] == "dharshan" for e in events_out)
    counts = manager.get_counts()
    assert counts["total_in"] == 1
    assert counts["total_out"] == 1
    assert counts["current_inside"] == 0
    assert "dharshan" not in manager._inside_employees
