# ============================================================
# FILE: movement_security/movement_evaluator.py
# PURPOSE: Evaluates tracked people against configurable zones,
#          employee permissions, and working hours to detect
#          unauthorized movement in real-time.
# USE CASE: Movement Security (Use Case 3)
#
# HOW IT WORKS:
#   - Loads zone polygons and rules from config/movement_rules.json.
#   - For each detected person, checks their footpoint (cx, y2) against
#     every configured zone polygon.
#   - Classifies each person: AUTHORISED, UNKNOWN, or UNAUTHORISED.
#   - Detects 4 violation types:
#       1. UNKNOWN_PERSON_DETECTION   → Unregistered person in a zone
#       2. UNAUTHORISED_MOVEMENT      → Employee without zone permission
#       3. AFTER_HOURS_MOVEMENT       → Anyone in a restricted zone outside working hours
#       (Restricted zone entry is a subtype of these)
#
# DEBUG TIPS:
#   - No alerts firing?
#       → Check config/movement_rules.json exists and is valid JSON.
#       → Check "enabled": true in movement_rules.json.
#       → Check zone polygons cover the area where people are detected.
#       → Check alert_cooldown (default 25s) — alerts are suppressed for 25s per person per zone.
#       → Increase LOG_LEVEL to DEBUG in .env to see per-frame zone checks.
#   - After-hours alerts during working hours?
#       → Check working_hours.start and working_hours.end in movement_rules.json.
#       → Server timezone: working hours are compared in UTC.
#   - Wrong employee identity?
#       → Check InsightFace recognition threshold in .env (FACE_MATCH_THRESHOLD).
#       → Check employee_roles mapping in movement_rules.json.
#   - Zone polygon not matching screen?
#       → Polygon points are in ABSOLUTE PIXELS (not normalized).
#       → Use scratch_faces/gate_coordinate_grid.jpg to find coordinates.
#   - Config changes not applying?
#       → movement_rules.json is reloaded on every evaluate() call if mtime changed.
#
# ALERT KEYS (for deduplication):
#   "{tracking_id}_{zone_id}_{violation_type}"
#   → Same person in same zone same violation type won't re-alert for 25s.
#
# DEPENDENCIES:
#   - config/movement_rules.json  → zones, rules, working hours
#   - cv2 (OpenCV)                           → pointPolygonTest, polygon drawing
# ============================================================

import cv2
import json
import logging
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

log = logging.getLogger(__name__)


class MovementSecurityEngine:
    """
    Real-time movement security evaluator.

    Classifies every tracked person per frame and generates alerts
    when unauthorized movement, unknown persons, or after-hours activity
    is detected in configured factory zones.

    Load: MovementSecurityEngine(config_path="config/movement_rules.json")
    Call: events = engine.evaluate(people, camera_id, camera_name)
    """

    def __init__(self, config_path: str = "config/movement_rules.json"):
        self.config_path = Path(config_path)
        self.config_mtime: Optional[float] = None
        self.enabled: bool = True
        self.working_hours: Dict[str, Any] = {}
        self.alert_cooldown: float = 25.0
        self.min_frames_in_zone: int = 2
        self.identity_resolution_grace_seconds: float = 3.0
        self.zones: List[Dict[str, Any]] = []
        self.employee_roles: Dict[str, str] = {}

        # Per-track state: {str(tracking_id): {frames_in_zone, last_seen, resolved_name, ...}}
        self._track_states: Dict[str, Dict[str, Any]] = {}
        # Alert cooldown: {alert_key: last_alert_timestamp}
        self._last_alert_time: Dict[str, float] = {}

        self.load_config()

    def load_config(self) -> None:
        """
        Load or hot-reload movement_rules.json if the file has changed on disk.

        DEBUG: Config not reloading?
               → File is only re-read when mtime changes.
               → Check config_path exists: config/movement_rules.json
               → Errors logged at ERROR level with full traceback.
        """
        if not self.config_path.exists():
            log.warning("Movement rules config not found at %s", self.config_path)
            return
        try:
            mtime = self.config_path.stat().st_mtime
            if mtime == self.config_mtime:
                return
            self.config_mtime = mtime
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.enabled = data.get("enabled", True)
            self.working_hours = data.get("working_hours", {})
            self.alert_cooldown = float(data.get("alert_cooldown_seconds", 25))
            self.min_frames_in_zone = int(data.get("min_frames_in_zone", 2))
            self.employee_roles = {k.lower(): v for k, v in data.get("employee_roles", {}).items()}
            parsed_zones = []
            for z in data.get("zones", []):
                poly = np.array(z.get("polygon", []), dtype=np.int32)
                if len(poly) >= 3:
                    parsed_zones.append({
                        "zone_id": z.get("zone_id", "unnamed_zone"),
                        "zone_name": z.get("zone_name", "Monitored Zone"),
                        "zone_type": z.get("zone_type", "CONTROLLED").upper(),
                        "polygon": poly,
                        "allowed_roles": set(r.lower() for r in z.get("allowed_roles", [])),
                        "allowed_employees": set(e.lower() for e in z.get("allowed_employees", [])),
                        "after_hours_restricted": z.get("after_hours_restricted", True),
                        "severity": z.get("severity", "HIGH").upper(),
                        "color": z.get("color", "#ef4444"),
                    })
            self.zones = parsed_zones
            log.info("Movement Security Engine: loaded %d zones from %s", len(self.zones), self.config_path)
        except Exception as exc:
            log.exception("Error loading movement security config: %s", exc)

    def is_working_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Returns True if dt (UTC) falls within configured working hours.

        DEBUG: Always returns True?
               → Check working_hours.enabled is true in movement_rules.json.
               → Confirm start/end strings are "HH:MM" format.
        """
        if not self.working_hours or not self.working_hours.get("enabled", True):
            return True
        if dt is None:
            dt = datetime.now(timezone.utc)
        try:
            start_str = self.working_hours.get("start", "08:00")
            end_str = self.working_hours.get("end", "19:00")
            curr_str = dt.strftime("%H:%M")
            return start_str <= curr_str <= end_str
        except Exception:
            return True

    def point_in_zone(self, point: Tuple[float, float], polygon: np.ndarray) -> bool:
        """Returns True if pixel point (x, y) is inside the polygon."""
        return cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), measureDist=False) >= 0

    def evaluate_person(self, person, camera_id, camera_name, now_ts, dt_utc) -> List[Dict]:
        """
        Evaluate one person's footpoint against all configured zones.

        Returns list of alert event dicts (empty if no violations).

        DEBUG: No events returned for a person in a restricted zone?
               → Check min_frames_in_zone (default 2) — person must be in zone for 2+ frames.
               → Check alert_cooldown — same alert won't fire again for 25s.
               → Check identity_resolution_grace_seconds (3s) — PENDING identity is ignored briefly.
        """
        tid = str(person.get("id"))
        box = person.get("box", [0, 0, 0, 0])
        cx = (box[0] + box[2]) / 2.0
        cy_foot = float(box[3])
        footpoint = (cx, cy_foot)

        emp_name = person.get("name")
        if not emp_name or emp_name.lower() in ("unknown", "unregistered", "none"):
            emp_name = None

        if tid not in self._track_states:
            self._track_states[tid] = {
                "first_seen": now_ts, "last_seen": now_ts,
                "frames_in_zone": {}, "resolved_name": emp_name,
            }
        st = self._track_states[tid]
        st["last_seen"] = now_ts
        if emp_name and not st.get("resolved_name"):
            st["resolved_name"] = emp_name

        resolved_name = st.get("resolved_name")
        resolved_name_lower = resolved_name.lower() if resolved_name else None
        emp_role = self.employee_roles.get(resolved_name_lower, "employee") if resolved_name_lower else None

        events = []
        is_operating = self.is_working_hours(dt_utc)

        for zone in self.zones:
            zid = zone["zone_id"]
            zname = zone["zone_name"]
            ztype = zone["zone_type"]
            in_zone = self.point_in_zone(footpoint, zone["polygon"])

            if not in_zone:
                st["frames_in_zone"][zid] = 0
                continue

            count = st["frames_in_zone"].get(zid, 0) + 1
            st["frames_in_zone"][zid] = count
            if count < self.min_frames_in_zone:
                continue

            has_permission = False
            if resolved_name_lower:
                if resolved_name_lower in zone["allowed_employees"]:
                    has_permission = True
                elif emp_role and emp_role in zone["allowed_roles"]:
                    has_permission = True

            violation_type = None
            severity = zone["severity"]
            desc = ""
            final_id_status = "AUTHORISED" if resolved_name else "UNKNOWN"

            if not is_operating and zone["after_hours_restricted"]:
                violation_type = "AFTER_HOURS_MOVEMENT"
                severity = "CRITICAL"
                final_id_status = "UNAUTHORISED"
                desc = f"Movement detected in {zname} during non-operational hours ({dt_utc.strftime('%H:%M')} UTC)."
            elif not resolved_name:
                violation_type = "UNKNOWN_PERSON_DETECTION"
                severity = "CRITICAL" if ztype == "RESTRICTED" else "HIGH"
                final_id_status = "UNKNOWN"
                desc = f"Unregistered / Unknown person detected inside {zname}."
            elif not has_permission:
                violation_type = "UNAUTHORISED_MOVEMENT"
                severity = zone["severity"]
                final_id_status = "UNAUTHORISED"
                desc = f"Employee {resolved_name} is unauthorized to enter {zname} (Role: {emp_role or 'none'})."

            if violation_type:
                # Grace period: skip alert if identity is still being resolved
                identity_pending = person.get("identity_state") == "PENDING" and not resolved_name
                if identity_pending and now_ts - st["first_seen"] < self.identity_resolution_grace_seconds:
                    continue

                alert_key = f"{tid}_{zid}_{violation_type}"
                if (now_ts - self._last_alert_time.get(alert_key, 0.0)) >= self.alert_cooldown:
                    self._last_alert_time[alert_key] = now_ts
                    events.append({
                        "camera_id": camera_id, "camera_name": camera_name,
                        "tracking_id": tid,
                        "employee_id": resolved_name_lower, "employee_name": resolved_name,
                        "identity_status": final_id_status,
                        "event_type": violation_type,
                        "zone_name": zname, "zone_id": zid,
                        "severity": severity, "description": desc,
                        "footpoint": footpoint, "bounding_box": box,
                        "confidence": person.get("confidence", 0.0),
                        "timestamp": now_ts, "event_timestamp": dt_utc,
                    })

        person["identity_status"] = "AUTHORISED" if resolved_name else "UNKNOWN"
        return events

    def evaluate(self, people, camera_id, camera_name) -> List[Dict]:
        """
        Evaluate all detected people in this frame.
        Cleans up stale tracks (not seen for > 15s).

        Returns:
            List of alert event dicts for all violations this frame.
        """
        if not self.enabled:
            return []
        self.load_config()  # hot-reload if config changed
        now_ts = datetime.now(timezone.utc).timestamp()
        dt_utc = datetime.now(timezone.utc)
        all_events = []
        for p in people:
            all_events.extend(self.evaluate_person(p, camera_id, camera_name, now_ts, dt_utc))
        # Prune stale tracks
        stale = [k for k, v in self._track_states.items() if (now_ts - v["last_seen"]) > 15.0]
        for k in stale:
            del self._track_states[k]
        return all_events

    def get_summary_counts(self, people) -> Dict[str, int]:
        """Live count breakdown: total, authorised, unknown, unauthorised."""
        total = len(people)
        authorised = unknown = unauthorised = 0
        for p in people:
            s = p.get("identity_status", "UNKNOWN")
            if s == "AUTHORISED":
                authorised += 1
            elif s == "UNAUTHORISED":
                unauthorised += 1
            else:
                unknown += 1
        return {"total_detected": total, "authorised_count": authorised, "unknown_count": unknown, "unauthorised_count": unauthorised}

    def annotate(self, frame, people) -> np.ndarray:
        """
        Draw zone polygons and color-coded person bounding boxes on frame.
        Green = Authorised, Yellow = Unknown, Red = Unauthorised.

        DEBUG: Zones not visible?
               → Check polygon points are valid absolute pixel coordinates.
               → Confirm frame is not None before calling annotate().
        """
        if frame is None or not self.enabled:
            return frame
        overlay = frame.copy()
        for zone in self.zones:
            poly = zone["polygon"]
            color = (0, 0, 220) if zone["zone_type"] == "RESTRICTED" else (0, 140, 255)
            cv2.polylines(frame, [poly], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)
            cv2.fillPoly(overlay, [poly], color=color)
            min_pt = poly.min(axis=0)
            cv2.putText(frame, f"{zone['zone_name']} [{zone['zone_type']}]",
                        (int(min_pt[0]) + 5, int(min_pt[1]) + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        for p in people:
            box = p.get("box")
            if not box or len(box) < 4:
                continue
            x1, y1, x2, y2 = [int(v) for v in box]
            status = p.get("identity_status", "UNKNOWN")
            box_color = (46, 204, 113) if status == "AUTHORISED" else (0, 0, 235) if status == "UNAUTHORISED" else (0, 215, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2, cv2.LINE_AA)
            name = p.get("name") or "Unknown"
            badge = f"ID:{p.get('id')} | {name} ({status})"
            (tw, th), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - 20)), (x1 + tw + 6, max(0, y1)), box_color, -1)
            cv2.putText(frame, badge, (x1 + 3, max(14, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (10, 10, 10), 1, cv2.LINE_AA)
        return frame
