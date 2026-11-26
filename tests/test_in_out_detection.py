import pytest
from entry_exit_headcount.headcount_manager import HeadcountManager

def test_known_and_unknown_in_and_out():
    """
    Verify that both known employees and unknown persons have their IN and OUT
    crossings properly detected, including when ByteTrack assigns a different
    tracking ID when exiting.
    """
    manager = HeadcountManager(
        gate_name="Gate 3",
        two_lines=False,
        line_start=(150, 560),
        line_end=(1050, 560),
        entry_direction="A_TO_B",
        confirmation_frames=1,
        cooldown=0.0,
        enforce_entry_first=False,
    )
    frame_shape = (720, 1280, 3)

    # 1. Unknown person enters at x=300 (moves from y=500 to y=620)
    manager.process([{"id": 1, "name": "Unknown", "box": [280, 450, 320, 520], "confidence": 0.85}], frame_shape)
    events_in_1 = manager.process([{"id": 1, "name": "Unknown", "box": [280, 580, 320, 650], "confidence": 0.85}], frame_shape)
    assert len(events_in_1) == 1
    assert events_in_1[0]["direction"] == "IN"
    assert events_in_1[0]["employee_name"] is None

    # 2. Known employee ("Dharshan") enters at x=800 (moves from y=480 to y=620)
    manager.process([{"id": 2, "name": "Dharshan", "box": [780, 440, 820, 510], "confidence": 0.92}], frame_shape)
    events_in_2 = manager.process([{"id": 2, "name": "Dharshan", "box": [780, 580, 820, 650], "confidence": 0.92}], frame_shape)
    assert len(events_in_2) == 1
    assert events_in_2[0]["direction"] == "IN"
    assert events_in_2[0]["employee_name"] == "Dharshan"

    # Current counts
    counts = manager.get_counts()
    assert counts["total_in"] == 2
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 2

    # 3. Known employee exits (moves from y=620 to y=480) with a NEW tracking ID (e.g. 50)
    manager.process([{"id": 50, "name": "Dharshan", "box": [780, 580, 820, 650], "confidence": 0.90}], frame_shape)
    events_out_known = manager.process([{"id": 50, "name": "Dharshan", "box": [780, 440, 820, 510], "confidence": 0.90}], frame_shape)
    assert len(events_out_known) == 1
    assert events_out_known[0]["direction"] == "OUT"
    assert events_out_known[0]["employee_name"] == "Dharshan"

    # 4. Unknown person exits (moves from y=630 to y=490) with a NEW tracking ID (e.g. 51)
    manager.process([{"id": 51, "name": None, "box": [280, 590, 320, 660], "confidence": 0.82}], frame_shape)
    events_out_unknown = manager.process([{"id": 51, "name": None, "box": [280, 450, 320, 520], "confidence": 0.82}], frame_shape)
    assert len(events_out_unknown) == 1
    assert events_out_unknown[0]["direction"] == "OUT"
    assert events_out_unknown[0]["employee_name"] is None

    # Final counts
    final_counts = manager.get_counts()
    assert final_counts["total_in"] == 2
    assert final_counts["total_out"] == 2
    assert final_counts["current_inside"] == 0

def test_gates_json_config_loading():
    """Verify that HeadcountManager loads line and threshold settings from entry_exit_headcount/gates.json."""
    manager = HeadcountManager()
    assert manager.line_start == (150, 560)
    assert manager.line_end == (1050, 560)
    assert manager.confidence_threshold == 0.30
    assert manager.confirmation_frames == 1
    assert manager.cooldown == 1.5
    assert manager.line_margin == 100
    assert manager.enforce_entry_first is False
