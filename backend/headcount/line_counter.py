
import math
import time
from collections import deque


class LineCounter:
    """
    Counts people entering and leaving through a virtual gate line.

    Direction rules:
        A_TO_B:
            Negative side -> Positive side = IN
            Positive side -> Negative side = OUT

        B_TO_A:
            Negative side -> Positive side = OUT
            Positive side -> Negative side = IN

    A crossing is counted only after the person remains on the
    opposite side for the configured confirmation_frames.
    """

    def __init__(
        self,
        line_start=(500, 100),
        line_end=(500, 900),
        entry_direction="A_TO_B",
        confirmation_frames=3,
        cooldown=3.0,
        history_size=30,
        line_margin=40,
    ):
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)

        self.entry_direction = entry_direction.upper()
        self.confirmation_frames = max(1, int(confirmation_frames))
        self.cooldown = float(cooldown)
        self.history_size = max(2, int(history_size))
        self.line_margin = float(line_margin)

        if self.entry_direction not in ("A_TO_B", "B_TO_A"):
            raise ValueError(
                "entry_direction must be 'A_TO_B' or 'B_TO_A'"
            )

        if self.line_start == self.line_end:
            raise ValueError("Gate line start and end cannot be the same")

        # Tracking information for each person.
        self.track_history = {}
        self.previous_sides = {}
        self.stable_points = {}
        self.crossing_candidates = {}
        self.last_count_time = {}
        self.last_seen_time = {}
        self.track_ttl = 5.0

        # Total counts.
        self.total_in = 0
        self.total_out = 0

    # ---------------------------------------------------------
    # GEOMETRY HELPERS
    # ---------------------------------------------------------

    def _side_of_line(self, point):
        """
        Returns:
            1  = Positive side
            -1 = Negative side
            0  = Exactly on the line
        """

        x1, y1 = self.line_start
        x2, y2 = self.line_end
        px, py = point

        cross_product = (
            (x2 - x1) * (py - y1)
            - (y2 - y1) * (px - x1)
        )

        if cross_product > 0:
            return 1

        if cross_product < 0:
            return -1

        return 0

    def _get_intersection(self, previous_point, current_point):
        """
        Calculates where the person's movement path intersects
        the virtual gate line.

        Returns intersection coordinates or None.
        """

        px, py = previous_point
        qx, qy = current_point

        ax, ay = self.line_start
        bx, by = self.line_end

        rx = qx - px
        ry = qy - py

        sx = bx - ax
        sy = by - ay

        denominator = rx * sy - ry * sx

        if abs(denominator) < 1e-9:
            return None

        t = ((ax - px) * sy - (ay - py) * sx) / denominator

        # The movement segment (0 <= t <= 1) must cross the gate line;
        # _is_crossing_gate checks whether the intersection falls within
        # the gate segment plus line_margin.
        if 0 <= t <= 1:
            intersection_x = px + t * rx
            intersection_y = py + t * ry

            return (intersection_x, intersection_y)

        return None

    def _is_crossing_gate(self, previous_point, current_point):
        """
        Checks whether movement crosses the actual gate segment,
        rather than an unlimited imaginary line.
        """

        intersection = self._get_intersection(
            previous_point,
            current_point
        )

        if intersection is None:
            return False

        ix, iy = intersection
        ax, ay = self.line_start
        bx, by = self.line_end

        line_length = math.hypot(bx - ax, by - ay)

        if line_length == 0:
            return False

        # Distance along the gate line to the intersection.
        projection = (
            ((ix - ax) * (bx - ax))
            + ((iy - ay) * (by - ay))
        ) / line_length

        return (
            -self.line_margin
            <= projection
            <= line_length + self.line_margin
        )

    def _get_direction(self, previous_side, current_side):
        """
        Determines whether the person is entering or leaving.
        """

        if previous_side == current_side:
            return None

        if self.entry_direction == "A_TO_B":
            if previous_side == -1 and current_side == 1:
                return "IN"

            if previous_side == 1 and current_side == -1:
                return "OUT"

        else:
            if previous_side == -1 and current_side == 1:
                return "OUT"

            if previous_side == 1 and current_side == -1:
                return "IN"

        return None

    # ---------------------------------------------------------
    # PERSON PROCESSING
    # ---------------------------------------------------------

    def process_person(self, person):
        """
        Processes one detected person.

        Expected person format:
        {
            "id": "tracking_id",
            "footpoint": (x, y),
            "confidence": 0.90
        }

        Returns a crossing event dictionary or None.
        """

        tracking_id = person.get("id")

        if tracking_id is None:
            return None

        tracking_id = str(tracking_id)

        # Use footpoint when available.
        footpoint = person.get("footpoint")

        # Otherwise calculate bottom-center from bounding box.
        if footpoint is None:
            box = person.get("box")

            if not box or len(box) != 4:
                return None

            x1, y1, x2, y2 = box

            footpoint = (
                (x1 + x2) / 2,
                y2
            )

        current_point = (
            float(footpoint[0]),
            float(footpoint[1])
        )
        self.last_seen_time[tracking_id] = time.time()

        current_side = self._side_of_line(current_point)

        # Ignore points exactly on the line.
        # Keep the previous stable side unchanged.
        if current_side == 0:
            return None

        # Save position history.
        if tracking_id not in self.track_history:
            self.track_history[tracking_id] = deque(
                maxlen=self.history_size
            )

        history = self.track_history[tracking_id]
        previous_point = history[-1] if history else None
        history.append(current_point)

        # First time seeing this person.
        if tracking_id not in self.previous_sides:
            self.previous_sides[tracking_id] = current_side
            self.stable_points[tracking_id] = current_point
            return None

        stable_side = self.previous_sides[tracking_id]

        # Person is still on the same side.
        if current_side == stable_side:
            self.stable_points[tracking_id] = current_point
            self.crossing_candidates.pop(tracking_id, None)
            return None

        # Check that the movement actually crossed the gate segment.
        candidate = self.crossing_candidates.get(tracking_id)

        if candidate is None:
            anchor_point = self.stable_points.get(tracking_id) or previous_point
            if anchor_point is None:
                return None

            if not self._is_crossing_gate(
                anchor_point,
                current_point
            ):
                return None

            candidate = {
                "side": current_side,
                "frames": 1,
                "previous_side": stable_side,
            }

            self.crossing_candidates[tracking_id] = candidate

        else:
            # The person must remain on the same new side.
            if current_side != candidate["side"]:
                self.crossing_candidates.pop(tracking_id, None)
                return None

            candidate["frames"] += 1

        # Wait until the new side is confirmed.
        if candidate["frames"] < self.confirmation_frames:
            return None

        direction = self._get_direction(
            candidate["previous_side"],
            candidate["side"]
        )

        # Update stable side after confirmation.
        self.previous_sides[tracking_id] = candidate["side"]
        self.stable_points[tracking_id] = current_point
        self.crossing_candidates.pop(tracking_id, None)

        if direction is None:
            return None

        # Prevent repeated counting during quick detection changes.
        current_time = time.time()
        last_time = self.last_count_time.get(tracking_id, 0)

        if current_time - last_time < self.cooldown:
            return None

        self.last_count_time[tracking_id] = current_time

        # Update totals.
        if direction == "IN":
            self.total_in += 1
        else:
            self.total_out += 1

        return {
            "tracking_id": tracking_id,
            "id": tracking_id,
            "direction": direction,
            "confidence": person.get("confidence"),
            "footpoint": current_point,
            "timestamp": current_time,
        }

    # ---------------------------------------------------------
    # PROCESS ALL PEOPLE
    # ---------------------------------------------------------

    def process(self, people):
        """
        Processes all detected people in the current frame.

        Returns a list of confirmed crossing events.
        """

        events = []

        for person in people:
            event = self.process_person(person)

            if event is not None:
                events.append(event)

        return events

    # ---------------------------------------------------------
    # COUNTS
    # ---------------------------------------------------------

    def get_counts(self):
        """Returns current IN and OUT totals."""

        return {
            "total_in": self.total_in,
            "total_out": self.total_out,
            "current_inside": max(
                0,
                self.total_in - self.total_out
            ),
        }

    def reset_counts(self):
        """Resets the IN and OUT totals."""

        self.total_in = 0
        self.total_out = 0

    # ---------------------------------------------------------
    # TRACK CLEANUP
    # ---------------------------------------------------------

    def cleanup_tracks(self, active_ids):
        """
        Removes tracking data for people no longer detected.

        active_ids should contain the IDs detected in the
        current frame.
        """

        active_ids = {str(track_id) for track_id in active_ids}
        now = time.time()
        ttl = max(self.track_ttl, self.cooldown * 2)

        tracked_ids = set(self.track_history.keys())

        inactive_ids = tracked_ids - active_ids

        for tracking_id in inactive_ids:
            # Keep track state alive during brief YOLO/ByteTrack occlusions
            if now - self.last_seen_time.get(tracking_id, 0) < ttl:
                continue
            self.track_history.pop(tracking_id, None)
            self.previous_sides.pop(tracking_id, None)
            self.stable_points.pop(tracking_id, None)
            self.crossing_candidates.pop(tracking_id, None)
            self.last_count_time.pop(tracking_id, None)
            self.last_seen_time.pop(tracking_id, None)
