# ============================================================
# FILE: backend/use_cases/perimeter/intrusion_detector.py
# PURPOSE: Detects leg-level (knee/ankle pose keypoints) and body
#          intrusions, boundary crossings, and zone approaches for
#          the configured perimeter zone.
# USE CASE: Perimeter Fencing (Use Case 1)
#
# IMPORTANT DESIGN RULE:
#   Face recognition (authorization) and perimeter intrusion are
#   SEPARATE decisions:
#     - Authorized employee outside zone        -> No alert
#     - Authorized employee's leg enters zone   -> "Leg Intrusion" alert
#     - Unknown person's leg enters zone        -> "Leg Intrusion - Unauthorised Person" alert
#     - Person body/foot enters zone            -> "Restricted Zone Intrusion" / "Boundary Crossing"
#
# DEBUG TIPS:
#   - Check zone polygon coords in config/zones.json.
#   - Check POSE_ENABLED=true and POSE_KEYPOINT_CONFIDENCE in .env.
#   - Tune ALERT_COOLDOWN in .env if repeated alerts are suppressed.
# ============================================================

from collections import defaultdict, deque
import time


class IntrusionDetector:
    """
    Evaluates each tracked person's leg keypoints (knees/ankles) and
    bottom-center point against the configured restricted perimeter zone.

    Face recognition (authorised vs unknown) is evaluated independently and
    NEVER bypasses a restricted-zone violation.
    """

    def __init__(self, zone, mode="crossing", approach_distance=35):
        self.zone = zone
        self.mode = mode
        self.approach_distance = approach_distance
        # {tracking_id: deque of (timestamp, inside_bool)}
        self.history = defaultdict(lambda: deque(maxlen=6))
        self.inside = set()
        self.leg_inside_ids = set()
        # {(tracking_id, event_type): last_alert_timestamp}
        self.last_alert = {}

    def _check_leg_keypoints(self, person, shape):
        """Return list of leg keypoint names currently inside the restricted zone."""
        leg_kpts = person.get("leg_keypoints") or {}
        inside_parts = []
        for part_name, kp in leg_kpts.items():
            if kp and len(kp) >= 2:
                if self.zone.inside((kp[0], kp[1]), shape):
                    inside_parts.append(part_name)
        return inside_parts

    def _min_distance_to_zone(self, person, shape):
        """Compute minimum distance from leg keypoints (or footpoint) to zone boundary."""
        points = [person["point"]]
        for kp in (person.get("leg_keypoints") or {}).values():
            if kp and len(kp) >= 2:
                points.append((kp[0], kp[1]))
        return min(self.zone.distance(pt, shape) for pt in points)

    def evaluate(self, person, shape, cooldown):
        """
        Evaluate one person for leg intrusion, zone intrusion, crossing, or approach.

        Returns:
            dict: {
                "inside": bool,
                "leg_inside": bool,
                "leg_parts_inside": list[str],
                "event": str | None,
                "direction": str | None,
                "zone": str,
                "authorised": bool,
                "employee_name": str | None,
            }
        """
        tid = person["id"]
        point = person["point"]

        # 1. Perimeter decision: check pose leg keypoints AND footpoint
        leg_parts_inside = self._check_leg_keypoints(person, shape)
        leg_inside = len(leg_parts_inside) > 0
        body_inside = self.zone.inside(point, shape)
        inside = leg_inside or body_inside

        hist = self.history[tid]
        previous = hist[-1][1] if hist else None
        hist.append((time.time(), inside))

        # 2. Authorization decision (SEPARATE from perimeter violation)
        has_identity_field = "name" in person
        emp_name = person.get("name")
        is_registered_emp = bool(emp_name and emp_name != "Unknown")
        is_auth = is_registered_emp or (
            hasattr(self.zone, "is_authorised") and self.zone.is_authorised(emp_name)
        )
        unauth_suffix = " - Unauthorised Person" if (has_identity_field and not is_auth) else ""

        event = None
        direction = None
        mode = self.zone.zone.get("mode", self.mode)

        # Priority 1: Leg keypoint (knee/ankle) entered restricted zone
        # Triggers for BOTH authorized employees AND unknown persons!
        if leg_inside:
            event = f"Leg Intrusion{unauth_suffix}"
            direction = f"Leg Entered Zone ({', '.join(leg_parts_inside)})"

        # Priority 2: Standard zone modes (when pose keypoints unavailable or approaching)
        elif mode == "crossing" and previous is not None and previous != inside:
            if inside:
                event = f"Boundary Crossing{unauth_suffix}"
                direction = "Outside to Inside"
            else:
                direction = "Inside to Outside"

        elif mode == "intrusion" and inside and tid not in self.inside:
            event = f"Restricted Zone Intrusion{unauth_suffix}"
            direction = "Outside to Inside"

        elif mode == "approach" and inside and tid not in self.inside:
            event = f"Restricted Zone Intrusion{unauth_suffix}"
            direction = "Outside to Inside"

        elif mode == "approach" and not inside and self._min_distance_to_zone(person, shape) <= self.approach_distance:
            event = f"Boundary Approach{unauth_suffix}"
            direction = "Approaching"

        if inside:
            self.inside.add(tid)
        else:
            self.inside.discard(tid)

        if leg_inside:
            self.leg_inside_ids.add(tid)
        else:
            self.leg_inside_ids.discard(tid)

        allowed = event and (time.time() - self.last_alert.get((tid, event), 0) >= cooldown)
        if allowed:
            self.last_alert[(tid, event)] = time.time()

        return {
            "inside": inside,
            "leg_inside": leg_inside,
            "leg_parts_inside": leg_parts_inside,
            "event": event if allowed else None,
            "direction": direction,
            "zone": self.zone.zone.get("name", "Restricted Area"),
            "authorised": is_auth,
            "employee_name": emp_name if is_registered_emp else None,
        }
