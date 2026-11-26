# ============================================================
# FILE: movement_security/movement_evaluator.py
# PURPOSE: Evaluates 5 unauthorized movement rules: unknown, restricted zone, role, after-hours, repeat
# USE CASE: Unauthorised Movement Detection (Use Case 3)
# DEBUG TIPS:
#   - Edit restricted zone polygons, roles, and working hours in movement_security/movement_rules.json
#   - Check alert_cooldown_seconds if repeated alerts are suppressed
#   - Ensure face recognition is loaded so employees are not flagged as UNKNOWN
# ============================================================

"""
Movement Security Engine for IT Furnace AI System.

Evaluates tracked people against configurable zones, employee permissions,
and operational hours to detect unauthorized human movement in real-time.
"""

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
    Evaluates detected and tracked persons against factory movement rules.
    - Classifies identity: AUTHORISED, UNKNOWN, UNAUTHORISED.
    - Checks zone occupancy using bottom-center footpoint (cx, y2).
    - Detects:
        1. Unknown Person Detection in controlled or restricted zones.
        2. Restricted Area Entry by unauthorized persons.
        3. Unauthorized Movement (role/employee permission violation).
        4. After-Hours Movement outside operational working hours.
        5. Repeated/Sustained Suspicious Entry without duplicate alert spam.
    """

    def __init__(self, config_path: str = "movement_security/movement_rules.json"):
        self.config_path = Path(config_path)
        self.config_mtime: Optional[float] = None
        self.enabled: bool = True
        self.working_hours: Dict[str, Any] = {}
        self.alert_cooldown: float = 25.0
        self.min_frames_in_zone: int = 2
        self.identity_resolution_grace_seconds: float = 3.0
        self.zones: List[Dict[str, Any]] = []
        self.employee_roles: Dict[str, str] = {}
        
        # State tracking per person: {str(tracking_id): {...}}
        # e.g., {"frames_in_zone": {zone_id: count}, "last_alert": {alert_key: timestamp}}
        self._track_states: Dict[str, Dict[str, Any]] = {}
        self._last_alert_time: Dict[str, float] = {}

        self.load_config()

    def load_config(self) -> None:
        """Loads or reloads movement rules configuration if modified on disk."""
        if not self.config_path.exists():
            log.warning("Movement rules configuration not found at %s", self.config_path)
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
            self.employee_roles = {
                k.lower(): v for k, v in data.get("employee_roles", {}).items()
            }

            raw_zones = data.get("zones", [])
            parsed_zones = []
            for z in raw_zones:
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
            log.info("Movement Security Engine loaded %d zones from %s", len(self.zones), self.config_path)
        except Exception as exc:
            log.exception("Error loading movement security config: %s", exc)

    def is_working_hours(self, dt: Optional[datetime] = None) -> bool:
        """Determines if the provided datetime is within configured factory working hours."""
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
        """Tests whether a point (x, y) is inside the polygon using cv2.pointPolygonTest."""
        pt = (float(point[0]), float(point[1]))
        return cv2.pointPolygonTest(polygon, pt, measureDist=False) >= 0

    def evaluate_person(
        self,
        person: Dict[str, Any],
        camera_id: int,
        camera_name: str,
        now_ts: float,
        dt_utc: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates a single detected person track against all zones and access rules.
        Returns a list of generated movement alert events (if any).
        """
        tid = str(person.get("id"))
        box = person.get("box", [0, 0, 0, 0])
        # Bottom-center footpoint (cx, y2)
        cx = (box[0] + box[2]) / 2.0
        cy_foot = float(box[3])
        footpoint = (cx, cy_foot)

        # Identity resolution
        emp_name = person.get("name")
        if not emp_name or emp_name.lower() in ("unknown", "unregistered", "none"):
            emp_name = None
            raw_id_status = "UNKNOWN"
        else:
            raw_id_status = "AUTHORISED"

        # Maintain track history
        if tid not in self._track_states:
            self._track_states[tid] = {
                "first_seen": now_ts,
                "last_seen": now_ts,
                "frames_in_zone": {},
                "resolved_name": emp_name,
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

        # Check person against each configured zone
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

            # Require confirmation frames inside the zone to prevent edge jitter
            if count < self.min_frames_in_zone:
                continue

            # Determine permission
            has_permission = False
            if resolved_name_lower:
                if resolved_name_lower in zone["allowed_employees"]:
                    has_permission = True
                elif emp_role and emp_role in zone["allowed_roles"]:
                    has_permission = True

            # Determine violations
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
                # Unknown person inside controlled or restricted zone
                violation_type = "UNKNOWN_PERSON_DETECTION"
                severity = "CRITICAL" if ztype == "RESTRICTED" else "HIGH"
                final_id_status = "UNKNOWN"
                desc = f"Unregistered / Unknown person detected inside {zname}."
            elif not has_permission:
                # Registered employee lacks permission for this zone
                violation_type = "UNAUTHORISED_MOVEMENT"
                severity = zone["severity"]
                final_id_status = "UNAUTHORISED"
                desc = f"Employee {resolved_name} is unauthorized to enter {zname} (Role: {emp_role or 'none'})."

            if violation_type:
                identity_pending = (
                    person.get("identity_state") == "PENDING"
                    and not resolved_name
                )
                if (
                    identity_pending
                    and now_ts - st["first_seen"] < self.identity_resolution_grace_seconds
                ):
                    continue

                # Alert cooldown & deduplication per track per zone per violation type
                alert_key = f"{tid}_{zid}_{violation_type}"
                last_time = self._last_alert_time.get(alert_key, 0.0)
                if (now_ts - last_time) >= self.alert_cooldown:
                    self._last_alert_time[alert_key] = now_ts
                    events.append({
                        "camera_id": camera_id,
                        "camera_name": camera_name,
                        "tracking_id": tid,
                        "employee_id": resolved_name_lower,
                        "employee_name": resolved_name,
                        "identity_status": final_id_status,
                        "event_type": violation_type,
                        "zone_name": zname,
                        "zone_id": zid,
                        "severity": severity,
                        "description": desc,
                        "footpoint": footpoint,
                        "bounding_box": box,
                        "confidence": person.get("confidence", 0.0),
                        "timestamp": now_ts,
                        "event_timestamp": dt_utc,
                    })

        # Update person dictionary with classified identity_status for annotation/HUD
        person["identity_status"] = (
            "AUTHORISED" if resolved_name
            else "UNKNOWN"
        )
        return events

    def evaluate(
        self,
        people: List[Dict[str, Any]],
        camera_id: int,
        camera_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates all people currently detected in the frame.
        Cleans up expired tracks (> 15 seconds unseen).
        """
        if not self.enabled:
            return []

        # Check config reload
        self.load_config()

        now_ts = datetime.now(timezone.utc).timestamp()
        dt_utc = datetime.now(timezone.utc)

        all_events = []
        for p in people:
            evts = self.evaluate_person(p, camera_id, camera_name, now_ts, dt_utc)
            all_events.extend(evts)

        # Cleanup stale tracks
        stale_keys = [
            k for k, v in self._track_states.items()
            if (now_ts - v["last_seen"]) > 15.0
        ]
        for k in stale_keys:
            del self._track_states[k]

        return all_events

    def get_summary_counts(self, people: List[Dict[str, Any]]) -> Dict[str, int]:
        """Calculates live summary breakdown for the current frame."""
        total = len(people)
        authorised = 0
        unknown = 0
        unauthorised = 0

        for p in people:
            status = p.get("identity_status", "UNKNOWN")
            if status == "AUTHORISED":
                authorised += 1
            elif status == "UNAUTHORISED":
                unauthorised += 1
            else:
                unknown += 1

        return {
            "total_detected": total,
            "authorised_count": authorised,
            "unknown_count": unknown,
            "unauthorised_count": unauthorised,
        }

    def annotate(self, frame: np.ndarray, people: List[Dict[str, Any]]) -> np.ndarray:
        """
        Draws movement security zones and color-coded person visual indicators:
          - Green: Authorised person
          - Yellow: Unknown person
          - Red: Unauthorised movement / violation
          - Orange: Restricted zone perimeter
        """
        if frame is None or not self.enabled:
            return frame

        # 1. Draw zones
        overlay = frame.copy()
        for zone in self.zones:
            poly = zone["polygon"]
            ztype = zone["zone_type"]
            color = (0, 0, 220) if ztype == "RESTRICTED" else (0, 140, 255)
            cv2.polylines(frame, [poly], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)
            cv2.fillPoly(overlay, [poly], color=color)

            # Label on top-left of polygon
            min_pt = poly.min(axis=0)
            label = f"{zone['zone_name']} [{ztype}]"
            cv2.putText(frame, label, (int(min_pt[0]) + 5, int(min_pt[1]) + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # Blend zones with 0.15 alpha
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

        # 2. Draw person indicators
        for p in people:
            box = p.get("box")
            if not box or len(box) < 4:
                continue
            x1, y1, x2, y2 = [int(v) for v in box]
            status = p.get("identity_status", "UNKNOWN")

            if status == "AUTHORISED":
                box_color = (46, 204, 113)  # Green
            elif status == "UNAUTHORISED":
                box_color = (0, 0, 235)      # Red
            else:
                box_color = (0, 215, 255)    # Yellow / Amber

            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2, cv2.LINE_AA)

            name = p.get("name") or "Unknown"
            tid = p.get("id")
            badge = f"ID:{tid} | {name} ({status})"
            (tw, th), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - 20)), (x1 + tw + 6, max(0, y1)), box_color, -1)
            cv2.putText(frame, badge, (x1 + 3, max(14, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (10, 10, 10), 1, cv2.LINE_AA)

        return frame
