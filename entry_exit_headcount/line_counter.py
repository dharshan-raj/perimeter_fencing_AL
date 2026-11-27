# ============================================================
# FILE: entry_exit_headcount/line_counter.py
# PURPOSE: Counts people crossing a virtual gate line drawn
#          across the camera frame. Handles both entry (IN)
#          and exit (OUT) directions using cross-product geometry.
# USE CASE: Entry/Exit Headcount (Use Case 2)
#
# HOW IT WORKS:
#   - For each person, computes which side of the line they are on.
#   - Detects when a person transitions from one side to the other.
#   - Requires confirmation_frames consecutive frames on the new side
#     before counting — reduces false positives from jitter.
#   - enforce_entry_first: an OUT event requires this person to have
#     previously triggered an IN event (prevents ghost exits).
#
# DEBUG TIPS:
#   - Counts not incrementing?
#       → Confirm line_start != line_end (raises ValueError if same).
#       → Check footpoint/lower_point is a valid (x, y) in frame pixels.
#       → Increase line_margin if person crosses near line endpoints.
#   - Double-counting?
#       → Reduce cooldown (default 3.0s). Increase confirmation_frames.
#   - Person counted as OUT without entering?
#       → Set enforce_entry_first=True in gates.json.
#   - Ghost tracks persisting?
#       → cleanup_tracks() removes tracks not seen for track_ttl seconds.
#
# ENTRY/EXIT DIRECTION RULES:
#   A_TO_B: Negative side → Positive side = IN
#   B_TO_A: Negative side → Positive side = OUT
#
# DEPENDENCIES:
#   - Called by: entry_exit_headcount/headcount_manager.py
# ============================================================

import math
import time
from collections import deque


class LineCounter:
    """
    Counts IN/OUT crossings over a virtual gate line defined by two pixel endpoints.

    Usage:
        counter = LineCounter(line_start=(500,100), line_end=(500,900))
        events = counter.process(people)   # list of person dicts with "footpoint"
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
        enforce_entry_first=False,
    ):
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)
        self.entry_direction = entry_direction.upper()
        self.confirmation_frames = max(1, int(confirmation_frames))
        self.cooldown = float(cooldown)
        self.history_size = max(2, int(history_size))
        self.line_margin = float(line_margin)

        if self.entry_direction not in ("A_TO_B", "B_TO_A"):
            raise ValueError("entry_direction must be 'A_TO_B' or 'B_TO_A'")
        if self.line_start == self.line_end:
            raise ValueError("Gate line start and end cannot be the same")

        # Per-person tracking state
        self.track_history = {}
        self.previous_sides = {}
        self.stable_points = {}
        self.crossing_candidates = {}
        self.last_count_time = {}
        self.last_seen_time = {}
        self.track_ttl = 5.0

        # Running totals
        self.total_in = 0
        self.total_out = 0

        # Strict entry-first enforcement: OUT requires a prior IN for this tracking ID
        self.enforce_entry_first = enforce_entry_first
        self.inside_tracking_ids = set()

    # ----------------------------------------------------------
    # GEOMETRY HELPERS
    # ----------------------------------------------------------

    def _side_of_line(self, point):
        """
        Cross-product sign determines which side of the line a point is on.
        Returns: 1 (positive side), -1 (negative side), 0 (exactly on line).
        """
        x1, y1 = self.line_start
        x2, y2 = self.line_end
        px, py = point
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return 1 if cross > 0 else (-1 if cross < 0 else 0)

    def _get_intersection(self, prev, curr):
        """Find where the movement path intersects the gate line segment."""
        px, py = prev
        qx, qy = curr
        ax, ay = self.line_start
        bx, by = self.line_end
        rx, ry = qx - px, qy - py
        sx, sy = bx - ax, by - ay
        denom = rx * sy - ry * sx
        if abs(denom) < 1e-9:
            return None
        t = ((ax - px) * sy - (ay - py) * sx) / denom
        if 0 <= t <= 1:
            return (px + t * rx, py + t * ry)
        return None

    def _is_crossing_gate(self, prev, curr):
        """
        True only if movement actually crosses within the gate segment
        (plus line_margin extension at each end).
        """
        pt = self._get_intersection(prev, curr)
        if pt is None:
            return False
        ix, iy = pt
        ax, ay = self.line_start
        bx, by = self.line_end
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            return False
        proj = ((ix - ax) * (bx - ax) + (iy - ay) * (by - ay)) / length
        return -self.line_margin <= proj <= length + self.line_margin

    def _get_direction(self, prev_side, curr_side):
        """Return 'IN', 'OUT', or None based on side transition and entry_direction."""
        if prev_side == curr_side:
            return None
        if self.entry_direction == "A_TO_B":
            if prev_side == -1 and curr_side == 1:
                return "IN"
            if prev_side == 1 and curr_side == -1:
                return "OUT"
        else:
            if prev_side == -1 and curr_side == 1:
                return "OUT"
            if prev_side == 1 and curr_side == -1:
                return "IN"
        return None

    # ----------------------------------------------------------
    # PERSON PROCESSING
    # ----------------------------------------------------------

    def process_person(self, person):
        """
        Evaluate one person for a confirmed gate crossing.

        Args:
            person (dict): Must contain "id" and either "footpoint" or "box".

        Returns:
            dict | None: Crossing event dict, or None if no confirmed crossing.

        DEBUG: Returns None always?
               → Check line_start != line_end.
               → Confirm footpoint is updated each frame (not same point).
               → Increase line_margin if person crosses near line endpoints.
        """
        tracking_id = person.get("id")
        if tracking_id is None:
            return None
        tracking_id = str(tracking_id)

        # Resolve footpoint
        footpoint = person.get("footpoint")
        if footpoint is None:
            box = person.get("box")
            if not box or len(box) != 4:
                return None
            x1, y1, x2, y2 = box
            footpoint = ((x1 + x2) / 2, y2)

        current_point = (float(footpoint[0]), float(footpoint[1]))
        self.last_seen_time[tracking_id] = time.time()
        current_side = self._side_of_line(current_point)

        # Ignore points on the line itself
        if current_side == 0:
            return None

        if tracking_id not in self.track_history:
            self.track_history[tracking_id] = deque(maxlen=self.history_size)

        history = self.track_history[tracking_id]
        previous_point = history[-1] if history else None
        history.append(current_point)

        # First sighting: establish baseline side
        if tracking_id not in self.previous_sides:
            self.previous_sides[tracking_id] = current_side
            self.stable_points[tracking_id] = current_point
            return None

        stable_side = self.previous_sides[tracking_id]
        if current_side == stable_side:
            self.stable_points[tracking_id] = current_point
            self.crossing_candidates.pop(tracking_id, None)
            return None

        # Check whether the actual gate segment was crossed
        candidate = self.crossing_candidates.get(tracking_id)
        if candidate is None:
            anchor = self.stable_points.get(tracking_id) or previous_point
            if anchor is None:
                return None
            if not self._is_crossing_gate(anchor, current_point):
                return None
            candidate = {"side": current_side, "frames": 1, "previous_side": stable_side}
            self.crossing_candidates[tracking_id] = candidate
        else:
            if current_side != candidate["side"]:
                self.crossing_candidates.pop(tracking_id, None)
                return None
            candidate["frames"] += 1

        # Require confirmation frames
        if candidate["frames"] < self.confirmation_frames:
            return None

        direction = self._get_direction(candidate["previous_side"], candidate["side"])
        self.previous_sides[tracking_id] = candidate["side"]
        self.stable_points[tracking_id] = current_point
        self.crossing_candidates.pop(tracking_id, None)

        if direction is None:
            return None

        # Enforce entry-first: OUT requires prior IN for this tracking ID
        if self.enforce_entry_first and direction == "OUT" and tracking_id not in self.inside_tracking_ids:
            return None

        # Cooldown: prevent duplicate counts within cooldown window
        now = time.time()
        if now - self.last_count_time.get(tracking_id, 0) < self.cooldown:
            return None

        self.last_count_time[tracking_id] = now
        if direction == "IN":
            self.total_in += 1
            self.inside_tracking_ids.add(tracking_id)
        else:
            self.total_out += 1
            self.inside_tracking_ids.discard(tracking_id)

        return {
            "tracking_id": tracking_id,
            "id": tracking_id,
            "direction": direction,
            "confidence": person.get("confidence"),
            "footpoint": current_point,
            "timestamp": now,
        }

    def process(self, people):
        """Process all detected people and return confirmed crossing events."""
        return [e for p in people if (e := self.process_person(p)) is not None]

    def get_counts(self):
        """Return current IN/OUT totals and computed inside count."""
        return {
            "total_in": self.total_in,
            "total_out": self.total_out,
            "current_inside": max(0, self.total_in - self.total_out),
        }

    def reset_counts(self):
        """Reset IN/OUT totals and inside tracking set."""
        self.total_in = 0
        self.total_out = 0
        self.inside_tracking_ids.clear()

    def cleanup_tracks(self, active_ids):
        """
        Remove tracking state for people not seen recently.

        DEBUG: Stale tracks causing phantom events?
               → track_ttl = max(5.0, cooldown*2). Reduce if needed.
        """
        active_ids = {str(tid) for tid in active_ids}
        now = time.time()
        ttl = max(self.track_ttl, self.cooldown * 2)
        for tid in list(self.track_history.keys()):
            if tid not in active_ids and now - self.last_seen_time.get(tid, 0) >= ttl:
                self.track_history.pop(tid, None)
                self.previous_sides.pop(tid, None)
                self.stable_points.pop(tid, None)
                self.crossing_candidates.pop(tid, None)
                self.last_count_time.pop(tid, None)
                self.last_seen_time.pop(tid, None)
