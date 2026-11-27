import pytest
from backend.use_cases.headcount.line_counter import LineCounter
from backend.use_cases.headcount.headcount_manager import HeadcountManager

def test_strict_entry_first_enforcement():
    # Initialize a counter with enforce_entry_first=True
    counter = LineCounter(
        line_start=(100, 200),
        line_end=(500, 200),
        entry_direction="A_TO_B",
        confirmation_frames=1,
        cooldown=0.0,
        enforce_entry_first=True,
    )

    # 1. Person 5 tries to EXIT without entering first (y=250 -> y=150)
    counter.process_person({"id": "5", "footpoint": (200, 250), "confidence": 0.9})
    evt_exit_unauthorized = counter.process_person({"id": "5", "footpoint": (200, 150), "confidence": 0.9})
    # Must NOT record OUT because they never entered!
    assert evt_exit_unauthorized is None
    counts = counter.get_counts()
    assert counts["total_in"] == 0
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 0

    # 2. Person 5 now ENTERS (y=150 -> y=250)
    counter.process_person({"id": "5", "footpoint": (200, 150), "confidence": 0.9})
    evt_enter = counter.process_person({"id": "5", "footpoint": (200, 250), "confidence": 0.9})
    assert evt_enter is not None
    assert evt_enter["direction"] == "IN"
    counts = counter.get_counts()
    assert counts["total_in"] == 1
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 1
    assert "5" in counter.inside_tracking_ids

    # 3. Person 5 now EXITS after having entered (y=250 -> y=150)
    evt_exit = counter.process_person({"id": "5", "footpoint": (200, 150), "confidence": 0.9})
    assert evt_exit is not None
    assert evt_exit["direction"] == "OUT"
    counts = counter.get_counts()
    assert counts["total_in"] == 1
    assert counts["total_out"] == 1
    assert counts["current_inside"] == 0
    assert "5" not in counter.inside_tracking_ids

    # 4. Person 5 stays outside (y=150) or moves further outside (y=120) and attempts OUT:
    evt_outside_move = counter.process_person({"id": "5", "footpoint": (200, 120), "confidence": 0.9})
    assert evt_outside_move is None
    assert counter.get_counts()["total_out"] == 1

    # 5. A brand new Person 9 appears on the inside and attempts to exit without entering
    counter.process_person({"id": "9", "footpoint": (200, 250), "confidence": 0.9})
    evt_unauthorized_exit = counter.process_person({"id": "9", "footpoint": (200, 150), "confidence": 0.9})
    assert evt_unauthorized_exit is None
    assert counter.get_counts()["total_out"] == 1
