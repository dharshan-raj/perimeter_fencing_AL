# ============================================================
# FILE: perimeter_fencing/intrusion_detector.py
# PURPOSE: Detects intrusions, boundary crossings, and zone
#          approaches for a configured perimeter zone.
# USE CASE: Perimeter Fencing (Use Case 1)
#
# HOW IT WORKS:
#   - For each detected person (from YOLO + ByteTrack),
#     checks if they crossed into or approached the zone.
#   - Authorised employees (from zones.json) do NOT trigger alerts.
#   - Three modes: "crossing", "intrusion", "approach"
#
# DEBUG TIPS:
#   - Alert not firing?
#       → Check zone mode in config/zones.json (crossing/intrusion/approach)
#       → Check alert_cooldown in .env (default 30s, may suppress rapid events)
#       → Confirm zone polygon points are correctly normalized [0.0–1.0]
#   - Alert fires for authorised employee?
#       → Check allowed_employees list in zones.json (must match face recognition name)
#   - Too many false positives?
#       → Increase approach_distance in .env or use "intrusion" mode instead of "crossing"
#   - Cooldown not working?
#       → Check self.last_alert dict; key is (tracking_id, event_type)
#
# DEPENDENCIES:
#   - perimeter_fencing/zone_manager.py  → ZoneManager.inside(), .distance()
#   - shared/config.py                   → settings.alert_cooldown
# ============================================================

from collections import defaultdict, deque
import time


class IntrusionDetector:
    """
    Evaluates each tracked person against the configured zone.
    Returns event type, direction, and authorisation status.

    Modes (set in zones.json):
        crossing  → Alert when person crosses the zone boundary (IN or OUT)
        intrusion → Alert only when a new person enters the zone
        approach  → Alert when person gets within approach_distance of zone
    """

    def __init__(self, zone, mode="crossing", approach_distance=35):
        self.zone = zone
        self.mode = mode
        self.approach_distance = approach_distance
        # {tracking_id: deque of (timestamp, inside_bool)}
        self.history = defaultdict(lambda: deque(maxlen=6))
        self.inside = set()
        # {(tracking_id, event_type): last_alert_timestamp}
        self.last_alert = {}

    def evaluate(self, person, shape, cooldown):
        """
        Evaluate one person for intrusion/crossing/approach events.

        Args:
            person (dict): {"id", "point", "confidence", "box", "name"(optional)}
            shape  (tuple): frame.shape — used to convert normalized zone coords
            cooldown (int): seconds between repeated alerts for same person+event

        Returns:
            dict: {
                "inside"    : bool,
                "event"     : str | None  (event name, or None if no alert),
                "direction" : str | None  ("Outside to Inside", "Inside to Outside", "Approaching"),
                "zone"      : str         (zone name from zones.json),
                "authorised": bool        (True = authorised employee, no alert)
            }

        DEBUG: If event is always None → check zone polygon in zones.json
               and confirm person["point"] is a valid [x, y] pixel coordinate.
        """
        tid = person["id"]
        point = person["point"]
        inside = self.zone.inside(point, shape)
        hist = self.history[tid]
        previous = hist[-1][1] if hist else None
        hist.append((time.time(), inside))

        event = None
        direction = None
        mode = self.zone.zone.get("mode", self.mode)

        # Authorised employees do not trigger intrusion/approach alerts
        emp_name = person.get("name")
        is_auth = hasattr(self.zone, "is_authorised") and self.zone.is_authorised(emp_name)

        if mode == "crossing" and previous is not None and previous != inside:
            event = ("Boundary Crossing" if not is_auth else None) if inside else None
            direction = "Outside to Inside" if inside else "Inside to Outside"

        elif mode == "intrusion" and inside and tid not in self.inside:
            event = "Restricted Zone Intrusion" if not is_auth else None
            direction = "Outside to Inside"

        elif mode == "approach" and not inside and self.zone.distance(point, shape) <= self.approach_distance:
            event = "Boundary Approach" if not is_auth else None
            direction = "Approaching"

        if inside:
            self.inside.add(tid)
        else:
            self.inside.discard(tid)

        allowed = event and time.time() - self.last_alert.get((tid, event), 0) >= cooldown
        if allowed:
            self.last_alert[(tid, event)] = time.time()

        return {
            "inside": inside,
            "event": event if allowed else None,
            "direction": direction,
            "zone": self.zone.zone.get("name", "Restricted Area"),
            "authorised": is_auth,
        }
