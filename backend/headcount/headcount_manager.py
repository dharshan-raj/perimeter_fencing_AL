import time
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from backend.headcount.headcount_detector import HeadcountDetector
from backend.headcount.line_counter import LineCounter

log = logging.getLogger(__name__)


class HeadcountManager:
    """
    Manages Gate 3 entry and exit headcount monitoring.

    Supports two lines:
      - Line IN: Dedicated Entry line (Green, marked '▶ IN')
      - Line OUT: Dedicated Exit line (Red, marked '◀ OUT')
    Reuses existing YOLOv8 and ByteTrack detections.
    """

    def __init__(
        self,
        gate_name="Gate 3",
        line_start=(500, 100),
        line_end=(500, 650),
        entry_direction="A_TO_B",
        confidence_threshold=0.35,
        confirmation_frames=3,
        cooldown=3.0,
        line_margin=40,
        two_lines=True,
        line_in_start=None,
        line_in_end=None,
        line_out_start=None,
        line_out_end=None,
    ):
        self.gate_name = gate_name
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)
        self.entry_direction = entry_direction
        self.confidence_threshold = confidence_threshold
        self.confirmation_frames = confirmation_frames
        self.cooldown = cooldown
        self.line_margin = line_margin

        self.two_lines = two_lines
        self.line_in_start = tuple(line_in_start) if line_in_start else None
        self.line_in_end = tuple(line_in_end) if line_in_end else None
        self.line_out_start = tuple(line_out_start) if line_out_start else None
        self.line_out_end = tuple(line_out_end) if line_out_end else None

        self._custom_config = bool(line_in_start or line_out_start or line_start != (500, 100))
        self._config_mtime = None
        self._last_config_check = 0.0

        # Load from config/gates.json if present and not custom configured
        if not self._custom_config:
            self._load_config()
        else:
            if self.line_in_start is None:
                self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))
                self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))
            if self.line_out_start is None:
                self.line_out_start = (self.line_start[0], self.line_start[1] + 25)
                self.line_out_end = (self.line_end[0], self.line_end[1] + 25)

        # Detector
        self.detector = HeadcountDetector(
            confidence_threshold=self.confidence_threshold
        )

        # Initialize counters
        self.total_in = 0
        self.total_out = 0
        self._last_gate_event = {}   # {tracking_id: (direction, timestamp)}
        # Camera-based IN (Channel 1) -> OUT (Channel 2) tracking state
        self._ch1_tracks = {}        # {tid: {"first_pos": (x,y), "frames": int, "counted": bool, "last_seen": float, "name": str|None}}
        self._ch2_tracks = {}        # {tid: {"first_pos": (x,y), "frames": int, "counted": bool, "last_seen": float, "name": str|None}}
        self._inside_employees = set()
        self._pending_in_count = 0
        self._last_in_name = None
        self._last_in_time = 0.0
        self._last_ch1_count_time = 0.0
        self._last_ch2_count_time = 0.0
        self._init_counters()

        self.enabled = True

    def _load_config(self):
        """Read gates.json to load single or dual gate line configurations."""
        if getattr(self, "_custom_config", False):
            return
        config_path = Path("config/gates.json")
        if not config_path.exists():
            # Derive default line_in and line_out if not set
            if self.line_in_start is None:
                self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))
                self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))
            if self.line_out_start is None:
                self.line_out_start = (self.line_start[0], self.line_start[1] + 25)
                self.line_out_end = (self.line_end[0], self.line_end[1] + 25)
            return

        try:
            mtime = config_path.stat().st_mtime
            if mtime == self._config_mtime:
                return
            self._config_mtime = mtime

            data = json.loads(config_path.read_text())
            gates = data.get("gates", [])
            if not gates:
                return

            g = gates[0]
            self.gate_name = g.get("gate_name", self.gate_name)
            self.two_lines = g.get("two_lines", True)

            # Single baseline
            line_data = g.get("line", {})
            if "start" in line_data:
                self.line_start = tuple(line_data["start"])
            if "end" in line_data:
                self.line_end = tuple(line_data["end"])
            if "entry_direction" in line_data:
                self.entry_direction = line_data["entry_direction"]

            # Line IN
            line_in_data = g.get("line_in", {})
            if "start" in line_in_data:
                self.line_in_start = tuple(line_in_data["start"])
            else:
                self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))

            if "end" in line_in_data:
                self.line_in_end = tuple(line_in_data["end"])
            else:
                self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))

            # Line OUT
            line_out_data = g.get("line_out", {})
            if "start" in line_out_data:
                self.line_out_start = tuple(line_out_data["start"])
            else:
                self.line_out_start = (self.line_start[0], self.line_start[1] + 25)

            if "end" in line_out_data:
                self.line_out_end = tuple(line_out_data["end"])
            else:
                self.line_out_end = (self.line_end[0], self.line_end[1] + 25)

            det_data = g.get("detection", {})
            self.confidence_threshold = det_data.get("confidence_threshold", self.confidence_threshold)
            self.confirmation_frames = det_data.get("confirmation_frames", self.confirmation_frames)
            self.cooldown = det_data.get("cooldown_seconds", self.cooldown)
            self.line_margin = det_data.get("line_margin", self.line_margin)

            if hasattr(self, "line_counter"):
                self._init_counters()

        except Exception as exc:
            log.warning("Could not parse config/gates.json: %s", exc)

    def _init_counters(self):
        """Initialize line counters for single or dual line operation."""
        # Single line counter
        self.line_counter = LineCounter(
            line_start=self.line_start,
            line_end=self.line_end,
            entry_direction=self.entry_direction,
            confirmation_frames=self.confirmation_frames,
            cooldown=self.cooldown,
            line_margin=self.line_margin,
        )

        if self.two_lines and self.line_in_start and self.line_out_start:
            # Dedicated IN counter
            self.line_in_counter = LineCounter(
                line_start=self.line_in_start,
                line_end=self.line_in_end,
                entry_direction="A_TO_B",
                confirmation_frames=self.confirmation_frames,
                cooldown=self.cooldown,
                line_margin=self.line_margin,
            )
            # Dedicated OUT counter
            self.line_out_counter = LineCounter(
                line_start=self.line_out_start,
                line_end=self.line_out_end,
                entry_direction="A_TO_B",
                confirmation_frames=self.confirmation_frames,
                cooldown=self.cooldown,
                line_margin=self.line_margin,
            )

    # -----------------------------------------------------
    # PROCESS CAMERA DETECTIONS
    # -----------------------------------------------------

    def process(self, people, frame_shape):
        """
        Process people detected by the camera manager.
        Returns list of confirmed IN/OUT events.
        """
        if not self.enabled:
            return []

        if not people:
            self.cleanup_tracks([])
            return []

        # Check for config reload every 2s
        if time.time() - self._last_config_check > 2.0:
            self._last_config_check = time.time()
            self._load_config()

        # Convert detections
        processed_people = self.detector.process(people, frame_shape)
        events = []

        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            # Use lower_point (y1 + 0.75*h) when available so tall bounding boxes
            # whose feet start below the upper doorway line still cross cleanly.
            line_people = [
                {**p, "footpoint": p.get("lower_point") or p.get("footpoint")}
                for p in processed_people
            ]
            raw_events = (
                self.line_in_counter.process(line_people)
                + self.line_out_counter.process(line_people)
            )
            same_dir_window = max(4.0, float(self.cooldown))
            opp_dir_window = float(self.cooldown)
            for evt in raw_events:
                direction = evt.get("direction")
                if direction not in ("IN", "OUT"):
                    continue
                tid = str(evt["tracking_id"])
                ts = evt.get("timestamp") or time.time()
                prev = self._last_gate_event.get(tid)
                if prev:
                    window = same_dir_window if prev[0] == direction else opp_dir_window
                    if (ts - prev[1]) < window:
                        continue
                self._last_gate_event[tid] = (direction, ts)
                if direction == "IN":
                    self.total_in += 1
                else:
                    self.total_out += 1
                evt["gate_name"] = self.gate_name
                evt["direction"] = direction
                evt["event_key"] = f"{self.gate_name}_{tid}_{direction}_{int(ts)}"
                evt["event_timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc)
                events.append(evt)
        else:
            # Fallback single line counter
            crossing_events = self.line_counter.process(processed_people)
            for evt in crossing_events:
                direction = evt.get("direction")
                if direction == "IN":
                    self.total_in += 1
                elif direction == "OUT":
                    self.total_out += 1
                evt["gate_name"] = self.gate_name
                ts = evt.get("timestamp") or time.time()
                evt["event_key"] = f"{self.gate_name}_{evt['tracking_id']}_{evt['direction']}_{int(ts)}"
                evt["event_timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc)
                events.append(evt)

        # Cleanup inactive tracks
        active_ids = [
            p["id"]
            for p in processed_people
            if p.get("id") is not None
        ]
        self.cleanup_tracks(active_ids)

        return events

    def process_in(self, people, frame_shape):
        """
        Channel 1 (IN Camera): Detects a person on Channel 1 and counts them as IN.
        Ignores stationary people sitting at desks; triggers once per person walking/entering.
        """
        if not self.enabled or not people:
            return []

        now = time.time()
        processed_people = self.detector.process(people, frame_shape)
        # Map raw names from camera_manager's people list
        name_by_id = {
            str(p.get("id")): p.get("name")
            for p in people
            if p.get("id") is not None and p.get("name") and p.get("name") != "Unknown"
        }

        events = []
        for p in processed_people:
            tid = str(p["id"])
            pos = p.get("center") or p.get("footpoint")
            if not pos:
                continue
            emp_name = name_by_id.get(tid)

            st = self._ch1_tracks.get(tid)
            if st is None:
                self._ch1_tracks[tid] = {
                    "first_pos": pos,
                    "frames": 1,
                    "counted": False,
                    "last_seen": now,
                    "name": emp_name,
                }
                continue

            st["frames"] += 1
            st["last_seen"] = now
            if emp_name:
                st["name"] = emp_name
                self._last_in_name = emp_name

            if st["counted"]:
                continue

            # Require at least 2 frames and >= 28px movement so seated desk workers aren't counted
            dx = pos[0] - st["first_pos"][0]
            dy = pos[1] - st["first_pos"][1]
            moved = (dx * dx + dy * dy) ** 0.5 >= 28.0

            if st["frames"] >= 2 and moved:
                if now - self._last_ch1_count_time < float(self.cooldown):
                    continue
                if st["name"] and st["name"] in self._inside_employees:
                    st["counted"] = True
                    continue

                st["counted"] = True
                self._last_ch1_count_time = now
                self.total_in += 1
                self._pending_in_count += 1
                if st["name"]:
                    self._inside_employees.add(st["name"])
                    self._last_in_name = st["name"]
                self._last_in_time = now

                events.append({
                    "tracking_id": tid,
                    "id": tid,
                    "employee_name": st["name"],
                    "direction": "IN",
                    "gate_name": self.gate_name,
                    "confidence": p.get("confidence"),
                    "timestamp": now,
                    "event_key": f"{self.gate_name}_CH1_{tid}_IN_{int(now)}",
                    "event_timestamp": datetime.fromtimestamp(now, tz=timezone.utc),
                })

        # Cleanup stale Channel 1 tracks unseen for > 8s
        self._ch1_tracks = {
            k: v for k, v in self._ch1_tracks.items() if now - v["last_seen"] <= 8.0
        }
        return events

    def process_out(self, people, frame_shape):
        """
        Channel 2 (OUT Camera): When a person (or the same person from Channel 1)
        is detected walking on Channel 2, counts them as OUT.
        """
        if not self.enabled or not people:
            return []

        now = time.time()
        processed_people = self.detector.process(people, frame_shape)
        name_by_id = {
            str(p.get("id")): p.get("name")
            for p in people
            if p.get("id") is not None and p.get("name") and p.get("name") != "Unknown"
        }

        events = []
        for p in processed_people:
            tid = str(p["id"])
            pos = p.get("center") or p.get("footpoint")
            if not pos:
                continue
            emp_name = name_by_id.get(tid)

            st = self._ch2_tracks.get(tid)
            if st is None:
                self._ch2_tracks[tid] = {
                    "first_pos": pos,
                    "frames": 1,
                    "counted": False,
                    "last_seen": now,
                    "name": emp_name,
                }
                continue

            st["frames"] += 1
            st["last_seen"] = now
            if emp_name:
                st["name"] = emp_name

            if st["counted"]:
                continue

            dx = pos[0] - st["first_pos"][0]
            dy = pos[1] - st["first_pos"][1]
            moved = (dx * dx + dy * dy) ** 0.5 >= 28.0

            # Trigger OUT if the same employee from Channel 1 is seen walking on Channel 2,
            # OR if a person entered on Channel 1 (_pending_in_count > 0) and is now walking on Channel 2,
            # OR if a person walks through the Channel 2 exit corridor (cx >= 580).
            same_employee = bool(st["name"] and st["name"] in self._inside_employees)
            in_exit_aisle = pos[0] >= 580
            can_count_out = same_employee or (self._pending_in_count > 0 and moved) or (in_exit_aisle and moved)

            if st["frames"] >= 2 and moved and can_count_out:
                if now - self._last_ch2_count_time < float(self.cooldown):
                    continue

                st["counted"] = True
                self._last_ch2_count_time = now
                self.total_out += 1
                if self._pending_in_count > 0:
                    self._pending_in_count -= 1

                resolved_name = st["name"]
                if not resolved_name and self._last_in_name and (now - self._last_in_time) < 300.0:
                    resolved_name = self._last_in_name
                if resolved_name:
                    self._inside_employees.discard(resolved_name)

                events.append({
                    "tracking_id": tid,
                    "id": tid,
                    "employee_name": resolved_name,
                    "direction": "OUT",
                    "gate_name": self.gate_name,
                    "confidence": p.get("confidence"),
                    "timestamp": now,
                    "event_key": f"{self.gate_name}_CH2_{tid}_OUT_{int(now)}",
                    "event_timestamp": datetime.fromtimestamp(now, tz=timezone.utc),
                })

        self._ch2_tracks = {
            k: v for k, v in self._ch2_tracks.items() if now - v["last_seen"] <= 8.0
        }
        return events

    # -----------------------------------------------------
    # ANNOTATE VIDEO FRAME (DRAW TWO MARKED LINES)
    # -----------------------------------------------------

    def _draw_top_counter_bar(self, frame, camera_label=None):
        """Draws ONLY the top IN / OUT counter badge without any floor lines."""
        if not self.enabled or frame is None:
            return frame
        try:
            import cv2
            counts = self.get_counts()
            prefix = f"{self.gate_name} ({camera_label})" if camera_label else self.gate_name
            text = f" {prefix}  |  IN: {counts['total_in']}   OUT: {counts['total_out']}   INSIDE: {counts['current_inside']} "
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.65
            thickness = 2
            (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
            bx, by = 16, th + 16
            cv2.rectangle(frame, (bx - 6, by - th - 8), (bx + tw + 6, by + 8), (15, 23, 42), -1)
            cv2.rectangle(frame, (bx - 6, by - th - 8), (bx + tw + 6, by + 8), (54, 210, 185), 2, cv2.LINE_AA)
            cv2.putText(frame, text, (bx, by), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        except Exception as exc:
            log.debug("Top counter annotation error: %s", exc)
        return frame

    def annotate(self, frame):
        """Draws the top IN / OUT summary badge on the video frame (no floor lines)."""
        return self._draw_top_counter_bar(frame)

    def annotate_in(self, frame):
        """Draws the top IN / OUT summary badge on Channel 1 (IN Camera)."""
        return self._draw_top_counter_bar(frame, "CH1 - IN")

    def annotate_out(self, frame):
        """Draws the top IN / OUT summary badge on Channel 2 (OUT Camera)."""
        return self._draw_top_counter_bar(frame, "CH2 - OUT")

    # -----------------------------------------------------
    # LIVE COUNTS
    # -----------------------------------------------------

    def get_counts(self):
        """Get current entry, exit and inside counts."""
        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            return {
                "gate_name": self.gate_name,
                "total_in": self.total_in,
                "total_out": self.total_out,
                "current_inside": max(0, self.total_in - self.total_out),
            }

        counts = self.line_counter.get_counts()
        return {
            "gate_name": self.gate_name,
            "total_in": counts["total_in"],
            "total_out": counts["total_out"],
            "current_inside": counts["current_inside"],
        }

    # -----------------------------------------------------
    # TRACK CLEANUP
    # -----------------------------------------------------

    def cleanup_tracks(self, active_ids):
        """Remove tracking information for inactive people."""
        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            self.line_in_counter.cleanup_tracks(active_ids)
            self.line_out_counter.cleanup_tracks(active_ids)

        self.line_counter.cleanup_tracks(active_ids)

    # -----------------------------------------------------
    # RESET COUNTS
    # -----------------------------------------------------

    def reset_counts(self):
        """Reset the headcount totals."""
        self.total_in = 0
        self.total_out = 0
        self._last_gate_event.clear()
        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            self.line_in_counter.reset_counts()
            self.line_out_counter.reset_counts()

        self.line_counter.reset_counts()

    # -----------------------------------------------------
    # ENABLE / DISABLE
    # -----------------------------------------------------

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    # -----------------------------------------------------
    # UPDATE GATE LINE
    # -----------------------------------------------------

    def update_gate_line(
        self,
        line_start,
        line_end,
        entry_direction="A_TO_B",
    ):
        """Update virtual gate line coordinates."""
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)
        self.entry_direction = entry_direction
        self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))
        self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))
        self.line_out_start = (self.line_start[0], self.line_start[1] + 25)
        self.line_out_end = (self.line_end[0], self.line_end[1] + 25)
        self._init_counters()
