
import pytest

from backend.headcount.line_counter import LineCounter


@pytest.fixture
def counter():
    """
    Create a headcount counter with a horizontal
    virtual line for testing.

    Negative side -> Positive side = IN
    Positive side -> Negative side = OUT
    """

    return LineCounter(
        line_start=(100, 200),
        line_end=(500, 200),
        entry_direction="A_TO_B",
        confirmation_frames=3,
        cooldown=0,
        line_margin=40,
    )


def make_person(tracking_id, x, y, confidence=0.90):
    """Create a sample tracked person."""

    return {
        "id": str(tracking_id),
        "footpoint": (x, y),
        "confidence": confidence,
    }


# --------------------------------------------------
# TEST 1: PERSON ENTERING
# --------------------------------------------------

def test_person_entering(counter):
    """
    Person moves from above the line to below it.
    Expected result: IN.
    """

    counter.process_person(make_person(1, 200, 150))

    counter.process_person(make_person(1, 200, 210))
    counter.process_person(make_person(1, 200, 220))

    event = counter.process_person(
        make_person(1, 200, 230)
    )

    assert event is not None
    assert event["direction"] == "IN"
    assert event["tracking_id"] == "1"

    counts = counter.get_counts()

    assert counts["total_in"] == 1
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 1


# --------------------------------------------------
# TEST 2: PERSON EXITING
# --------------------------------------------------

def test_person_exiting(counter):
    """
    Person moves from below the line to above it.
    Expected result: OUT.
    """

    counter.process_person(make_person(2, 200, 250))

    counter.process_person(make_person(2, 200, 190))
    counter.process_person(make_person(2, 200, 180))

    event = counter.process_person(
        make_person(2, 200, 170)
    )

    assert event is not None
    assert event["direction"] == "OUT"

    counts = counter.get_counts()

    assert counts["total_out"] == 1


# --------------------------------------------------
# TEST 3: PERSON NOT CROSSING
# --------------------------------------------------

def test_person_not_crossing(counter):
    """
    Person remains on the same side.
    Expected result: no event.
    """

    counter.process_person(make_person(3, 200, 100))

    event = counter.process_person(
        make_person(3, 250, 120)
    )

    assert event is None

    counts = counter.get_counts()

    assert counts["total_in"] == 0
    assert counts["total_out"] == 0


# --------------------------------------------------
# TEST 4: CROSSING NEEDS CONFIRMATION
# --------------------------------------------------

def test_crossing_confirmation(counter):
    """
    Crossing must be confirmed for three frames.
    """

    counter.process_person(make_person(4, 200, 150))

    first = counter.process_person(
        make_person(4, 200, 210)
    )

    second = counter.process_person(
        make_person(4, 200, 220)
    )

    third = counter.process_person(
        make_person(4, 200, 230)
    )

    assert first is None
    assert second is None
    assert third is not None
    assert third["direction"] == "IN"


# --------------------------------------------------
# TEST 5: MULTIPLE PEOPLE
# --------------------------------------------------

def test_multiple_people(counter):
    """
    Two different tracking IDs cross the gate.
    Both should be counted independently.
    """

    people_before = [
        make_person(10, 200, 150),
        make_person(11, 300, 150),
    ]

    counter.process(people_before)

    people_crossing_1 = [
        make_person(10, 200, 210),
        make_person(11, 300, 210),
    ]

    counter.process(people_crossing_1)

    people_crossing_2 = [
        make_person(10, 200, 220),
        make_person(11, 300, 220),
    ]

    counter.process(people_crossing_2)

    events = counter.process([
        make_person(10, 200, 230),
        make_person(11, 300, 230),
    ])

    assert len(events) == 2

    counts = counter.get_counts()

    assert counts["total_in"] == 2
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 2


# --------------------------------------------------
# TEST 6: REVERSE DIRECTION
# --------------------------------------------------

def test_person_can_enter_and_exit(counter):
    """
    A person enters and then exits.
    Both events should be counted.
    """

    counter.process_person(make_person(20, 200, 150))

    # Enter.
    counter.process_person(make_person(20, 200, 210))
    counter.process_person(make_person(20, 200, 220))

    in_event = counter.process_person(
        make_person(20, 200, 230)
    )

    assert in_event["direction"] == "IN"

    # Exit.
    counter.process_person(make_person(20, 200, 190))
    counter.process_person(make_person(20, 200, 180))

    out_event = counter.process_person(
        make_person(20, 200, 170)
    )

    assert out_event is not None
    assert out_event["direction"] == "OUT"

    counts = counter.get_counts()

    assert counts["total_in"] == 1
    assert counts["total_out"] == 1
    assert counts["current_inside"] == 0


# --------------------------------------------------
# TEST 7: RESET COUNTS
# --------------------------------------------------

def test_reset_counts(counter):
    """Reset the IN and OUT totals."""

    counter.process_person(make_person(30, 200, 150))

    counter.process_person(make_person(30, 200, 210))
    counter.process_person(make_person(30, 200, 220))
    counter.process_person(make_person(30, 200, 230))

    counter.reset_counts()

    counts = counter.get_counts()

    assert counts["total_in"] == 0
    assert counts["total_out"] == 0
    assert counts["current_inside"] == 0


# --------------------------------------------------
# TEST 8: INVALID DIRECTION
# --------------------------------------------------

def test_invalid_entry_direction():
    """Invalid gate direction should raise an error."""

    with pytest.raises(ValueError):
        LineCounter(
            line_start=(100, 200),
            line_end=(500, 200),
            entry_direction="INVALID",
        )


# --------------------------------------------------
# TEST 9: INVALID GATE LINE
# --------------------------------------------------

def test_invalid_gate_line():
    """A line cannot start and end at the same point."""

    with pytest.raises(ValueError):
        LineCounter(
            line_start=(200, 200),
            line_end=(200, 200),
        )


# --------------------------------------------------
# TEST 10: DUAL LINES (IN LINE AND OUT LINE)
# --------------------------------------------------

def test_two_lines_in_and_out():
    """Verify that HeadcountManager detects IN on line_in and OUT on line_out."""
    import numpy as np
    from backend.headcount.headcount_manager import HeadcountManager

    manager = HeadcountManager(
        gate_name="Gate 3",
        two_lines=True,
        line_in_start=(100, 150),
        line_in_end=(500, 150),
        line_out_start=(100, 300),
        line_out_end=(500, 300),
        confirmation_frames=1,
        cooldown=0.0,
    )

    frame_shape = (720, 1280, 3)

    # 1. Person 1 crosses Line IN from y=100 to y=180 (A_TO_B = IN)
    manager.process([{"id": 1, "box": [200, 80, 220, 120], "confidence": 0.9}], frame_shape)
    events_in = manager.process([{"id": 1, "box": [200, 160, 220, 200], "confidence": 0.9}], frame_shape)

    assert any(e["direction"] == "IN" for e in events_in)

    # 2. Person 2 crosses Line OUT from y=350 to y=250 (B_TO_A = OUT)
    manager.process([{"id": 2, "box": [200, 330, 220, 370], "confidence": 0.9}], frame_shape)
    events_out = manager.process([{"id": 2, "box": [200, 230, 220, 270], "confidence": 0.9}], frame_shape)

    assert any(e["direction"] == "OUT" for e in events_out)

    # Counts
    counts = manager.get_counts()
    assert counts["total_in"] == 1
    assert counts["total_out"] == 1

    # 3. Annotation draws on frame without error
    frame = np.zeros(frame_shape, dtype=np.uint8)
    annotated = manager.annotate(frame)
    assert annotated is not None
    assert annotated.shape == frame_shape
