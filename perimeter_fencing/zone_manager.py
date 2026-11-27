# ============================================================
# FILE: perimeter_fencing/zone_manager.py
# PURPOSE: Manages the perimeter zone polygon — loading from
#          JSON, updating via API, and geometric point-in-zone
#          and distance checks used by IntrusionDetector.
# USE CASE: Perimeter Fencing (Use Case 1)
#
# HOW IT WORKS:
#   - Loads zone definition from perimeter_fencing/zones.json on startup.
#   - Provides inside(), distance(), annotate() helpers called per frame.
#   - Zone polygon points are normalized [0.0–1.0] and scaled to frame size.
#
# DEBUG TIPS:
#   - Zone not loading?
#       → Check perimeter_fencing/zones.json exists and is valid JSON.
#       → If missing, DEFAULT zone (right 25% of frame) is used automatically.
#   - Person always "inside" or always "outside"?
#       → Open scratch_faces/gate_coordinate_grid.jpg to visualize pixel coords.
#       → Confirm zone "points" are normalized [0.0–1.0] not raw pixels.
#   - Zone doesn't update after API call?
#       → ZoneManager.update() saves to zones.json and returns updated zone.
#       → Restart camera_manager if zone not reloaded.
#   - Annotate not visible?
#       → Confirm frame is a valid BGR numpy array before calling annotate().
#
# DEPENDENCIES:
#   - perimeter_fencing/zones.json  → zone polygon + mode + allowed_employees
#   - cv2 (OpenCV)                  → polygon fill, text, pointPolygonTest
# ============================================================

import json
from pathlib import Path
import cv2
import numpy as np

# Default zone = right 25% column of the frame
DEFAULT = {
    "name": "Restricted Area",
    "mode": "crossing",
    "allowed_employees": ["dharshan"],
    "points": [[.72, .3], [.98, .3], [.98, .98], [.72, .98]],
}


class ZoneManager:
    """
    Loads and manages the perimeter zone definition.
    Call inside(point, shape) each frame to check zone membership.
    Call annotate(frame) to draw the zone overlay onto a video frame.
    """

    def __init__(self, path="perimeter_fencing/zones.json"):
        self.path = Path(path)
        self.zone = DEFAULT.copy()
        try:
            self.zone = json.loads(self.path.read_text())
        except (OSError, ValueError):
            # zones.json missing or corrupt → use DEFAULT silently
            pass

    def is_authorised(self, employee_name):
        """
        Returns True if employee_name is in the zone's allowed_employees list.

        DEBUG: If an employee is NOT being skipped:
               → Check employee name capitalisation (comparison is case-insensitive).
               → Confirm face recognition is returning the correct name string.
        """
        if not employee_name or employee_name == "Unknown":
            return False
        allowed = [e.lower() for e in self.zone.get("allowed_employees", ["dharshan"])]
        return employee_name.strip().lower() in allowed

    def update(self, zone):
        """
        Validate and persist a new zone definition from the API.
        Raises ValueError with a descriptive message on bad input.

        DEBUG: 422 error from API → check points are >= 3 and all values in [0,1].
        """
        pts = zone.get("points", [])
        if len(pts) < 3 or any(len(p) != 2 or not all(0 <= float(v) <= 1 for v in p) for p in pts):
            raise ValueError("Zone requires 3+ normalized points in [0,1]")
        if zone.get("mode", "crossing") not in ("crossing", "intrusion", "approach"):
            raise ValueError("Invalid boundary mode")
        allowed = zone.get("allowed_employees", self.zone.get("allowed_employees", ["dharshan"]))
        self.zone = {
            "name": zone.get("name", "Restricted Area"),
            "mode": zone.get("mode", "crossing"),
            "allowed_employees": allowed,
            "points": pts,
        }
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.zone, indent=2))
        return self.zone

    def polygon(self, shape):
        """Convert normalized zone points to absolute pixel coordinates for the given frame shape."""
        h, w = shape[:2]
        return np.array(
            [[int(float(x) * w), int(float(y) * h)] for x, y in self.zone["points"]],
            dtype=np.int32,
        )

    def inside(self, point, shape):
        """
        Returns True if point (x, y) is inside the zone polygon.
        point must be in absolute pixel coordinates matching frame shape.
        """
        return cv2.pointPolygonTest(self.polygon(shape), tuple(map(float, point)), False) >= 0

    def distance(self, point, shape):
        """
        Returns the distance (px) from point to the nearest zone edge.
        Used by 'approach' mode in IntrusionDetector.
        """
        poly = self.polygon(shape)
        return min(abs(cv2.pointPolygonTest(poly, tuple(map(float, point)), True)), 100000)

    def annotate(self, frame, is_intrusion=False):
        """
        Draws the zone polygon overlay on the video frame.
        - Red fill + 'INTRUSION!' label when is_intrusion=True
        - Orange fill + zone name label otherwise

        DEBUG: If zone is not visible on stream:
               → Confirm frame is not None and is a valid BGR numpy array.
               → Check zone polygon points cover a visible area of the frame.
        """
        poly = self.polygon(frame.shape)
        overlay = frame.copy()
        fill_color = (0, 0, 180) if is_intrusion else (0, 140, 255)
        border_color = (0, 0, 255) if is_intrusion else (0, 200, 255)
        cv2.fillPoly(overlay, [poly], fill_color)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.polylines(frame, [poly], True, border_color, 2, cv2.LINE_AA)
        top_idx = int(np.argmin(poly[:, 1]))
        tx, ty = int(poly[top_idx][0]), max(22, int(poly[top_idx][1]) - 8)
        name = self.zone.get("name", "Restricted Area")
        text = f"PERIMETER: {name}" + (" [INTRUSION!]" if is_intrusion else "")
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (tx - 4, ty - th - 5), (tx + tw + 4, ty + 3), (15, 23, 42), -1)
        cv2.rectangle(frame, (tx - 4, ty - th - 5), (tx + tw + 4, ty + 3), border_color, 1)
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, border_color, 1, cv2.LINE_AA)
        return frame
