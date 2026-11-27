# ============================================================
# FILE: entry_exit_headcount/headcount_manager.py
# PURPOSE: Orchestrates Gate 3 entry/exit headcount using
#          one or two virtual counting lines (IN line + OUT line).
#          Reuses YOLO+ByteTrack detections — no second camera needed.
# USE CASE: Entry/Exit Headcount (Use Case 2)
#
# HOW IT WORKS:
#   - On startup, reads entry_exit_headcount/gates.json for line coords.
#   - Two-line mode: separate GREEN (IN) and RED (OUT) counting lines.
#   - Single-line mode: one line counts both directions by side of crossing.
#   - process_in() / process_out(): separate methods for dual-camera setup
#     (Channel 1 = IN camera, Channel 2 = OUT camera).
#   - Tracks "inside" employees by name and tracking ID.
#
# DEBUG TIPS:
#   - Counts not incrementing?
#       → Check gates.json has valid line_in and line_out coords.
#       → Confirm people list is passed from camera_manager (not empty).
#       → Confirm enabled=True (default). Call manager.enable() if needed.
#   - Duplicate IN/OUT events?
#       → Increase cooldown in gates.json (detection.cooldown_seconds).
#       → same_dir_window (4s) prevents double-count on same direction.
#   - Person counted OUT without entering?
#       → Check enforce_entry_first in gates.json (detection section).
#       → Check self._inside_employees set includes the employee.
#   - Channel 1 / Channel 2 not working?
#       → Set dual_gate_cameras=True and source_in in .env.
#       → process_in() triggers on movement (>= 28px), not just detection.
#   - Gate line position wrong?
#       → Edit gates.json and restart — config is hot-reloaded every 2s.
#       → Use scratch_faces/gate_coordinate_grid.jpg to find pixel coords.
#
# DEPENDENCIES:
#   - entry_exit_headcount/headcount_detector.py  → HeadcountDetector
#   - entry_exit_headcount/line_counter.py         → LineCounter
#   - entry_exit_headcount/gates.json              → line coordinates
# ============================================================

import time
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from entry_exit_headcount.headcount_detector import HeadcountDetector
from entry_exit_headcount.line_counter import LineCounter

log = logging.getLogger(__name__)


class HeadcountManager:
    """
    Gate 3 entry/exit headcount manager.

    Supports:
      - Single virtual line (counts both IN and OUT by direction)
      - Dual lines: separate IN line (green) and OUT line (red)
      - Dual cameras: Channel 1 for IN, Channel 2 for OUT

    Call process() each frame with the detected people list.
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
        enforce_entry_first=True,
    ):
        self.gate_name = gate_name
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)
        self.entry_direction = entry_direction
        self.confidence_threshold = confidence_threshold
        self.confirmation_frames = confirmation_frames
        self.cooldown = cooldown
        self.line_margin = line_margin
        self.enforce_entry_first = enforce_entry_first

        self.two_lines = two_lines
        self.line_in_start = tuple(line_in_start) if line_in_start else None
        self.line_in_end = tuple(line_in_end) if line_in_end else None
        self.line_out_start = tuple(line_out_start) if line_out_start else None
        self.line_out_end = tuple(line_out_end) if line_out_end else None

        self._custom_config = bool(line_in_start or line_out_start or line_start != (500, 100))
        self._config_mtime = None
        self._last_config_check = 0.0

        # Load from gates.json if no custom config was passed
        if not self._custom_config:
            self._load_config()
        else:
            if self.line_in_start is None:
                self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))
                self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))
            if self.line_out_start is None:
                self.line_out_start = (self.line_start[0], self.line_start[1] + 25)
                self.line_out_end = (self.line_end[0], self.line_end[1] + 25)

        self.detector = HeadcountDetector(confidence_threshold=self.confidence_threshold)

        # Running totals
        self.total_in = 0
        self.total_out = 0

        # Per-track state for dual-camera mode
        self._last_gate_event = {}       # {tid: (direction, timestamp)}
        self._ch1_tracks = {}            # {tid: {first_pos, frames, counted, last_seen, name}}
        self._ch2_tracks = {}
        self._inside_employees = set()   # employee names currently inside
        self._pending_in_count = 0
        self._last_in_name = None
        self._last_in_time = 0.0
        self._last_ch1_count_time = 0.0
        self._last_ch2_count_time = 0.0
        self._init_counters()

        self.enabled = True

    def _load_config(self):
        """
        Read entry_exit_headcount/gates.json for gate line configuration.
        Hot-reloaded every 2 seconds during runtime.

        DEBUG: Config not reloading?
               → Check file path: entry_exit_headcount/gates.json
               → Errors logged as WARNING: "Could not parse gates.json: ..."
        """
        if getattr(self, "_custom_config", False):
            return
        config_path = Path("entry_exit_headcount/gates.json")
        if not config_path.exists():
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

            line_data = g.get("line", {})
            if "start" in line_data:
                self.line_start = tuple(line_data["start"])
            if "end" in line_data:
                self.line_end = tuple(line_data["end"])
            if "entry_direction" in line_data:
                self.entry_direction = line_data["entry_direction"]

            line_in_data = g.get("line_in", {})
            self.line_in_start = tuple(line_in_data["start"]) if "start" in line_in_data else (self.line_start[0], max(0, self.line_start[1] - 25))
            self.line_in_end = tuple(line_in_data["end"]) if "end" in line_in_data else (self.line_end[0], max(0, self.line_end[1] - 25))

            line_out_data = g.get("line_out", {})
            self.line_out_start = tuple(line_out_data["start"]) if "start" in line_out_data else (self.line_start[0], self.line_start[1] + 25)
            self.line_out_end = tuple(line_out_data["end"]) if "end" in line_out_data else (self.line_end[0], self.line_end[1] + 25)

            det_data = g.get("detection", {})
            self.confidence_threshold = det_data.get("confidence_threshold", self.confidence_threshold)
            self.confirmation_frames = det_data.get("confirmation_frames", self.confirmation_frames)
            self.cooldown = det_data.get("cooldown_seconds", self.cooldown)
            self.line_margin = det_data.get("line_margin", self.line_margin)
            self.enforce_entry_first = det_data.get("enforce_entry_first", False)

            if hasattr(self, "detector") and self.detector is not None:
                self.detector.confidence_threshold = self.confidence_threshold
            if hasattr(self, "line_counter"):
                self._init_counters()

        except Exception as exc:
            log.warning("Could not parse entry_exit_headcount/gates.json: %s", exc)

    def _init_counters(self):
        """Initialize line counter objects for single or dual line mode."""
        if self.line_start == self.line_end:
            self.line_end = (self.line_start[0] + 300, self.line_start[1])
        if self.line_in_start and self.line_in_start == self.line_in_end:
            self.line_in_end = (self.line_in_start[0] + 300, self.line_in_start[1])
        if self.line_out_start and self.line_out_start == self.line_out_end:
            self.line_out_end = (self.line_out_start[0] + 300, self.line_out_start[1])

        self.line_counter = LineCounter(
            line_start=self.line_start,
            line_end=self.line_end,
            entry_direction=self.entry_direction,
            confirmation_frames=self.confirmation_frames,
            cooldown=self.cooldown,
            line_margin=self.line_margin,
            enforce_entry_first=getattr(self, "enforce_entry_first", False),
        )

        if self.two_lines and self.line_in_start and self.line_out_start:
            self.line_in_counter = LineCounter(
                line_start=self.line_in_start,
                line_end=self.line_in_end,
                entry_direction="A_TO_B",
                confirmation_frames=self.confirmation_frames,
                cooldown=self.cooldown,
                line_margin=self.line_margin,
                enforce_entry_first=False,
            )
            self.line_out_counter = LineCounter(
                line_start=self.line_out_start,
                line_end=self.line_out_end,
                entry_direction="A_TO_B",
                confirmation_frames=self.confirmation_frames,
                cooldown=self.cooldown,
                line_margin=self.line_margin,
                enforce_entry_first=False,
            )

    # ----------------------------------------------------------
    # MAIN FRAME PROCESSING (single camera)
    # ----------------------------------------------------------

    def process(self, people, frame_shape):
        """
        Process people from one camera with either single or dual virtual lines.
        Returns list of confirmed IN/OUT crossing events.
        """
        if not self.enabled:
            return []
        if not people:
            self.cleanup_tracks([])
            return []

        # Hot-reload config every 2 seconds
        if time.time() - self._last_config_check > 2.0:
            self._last_config_check = time.time()
            self._load_config()

        processed_people = self.detector.process(people, frame_shape)
        name_by_id = {
            str(p.get("id")): p.get("name")
            for p in people
            if p.get("id") is not None and p.get("name") and p.get("name") != "Unknown"
        }
        events = []

        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            line_people = [
                {**p, "footpoint": p.get("lower_point") or p.get("footpoint")}
                for p in processed_people
            ]
            raw_events = self.line_in_counter.process(line_people) + self.line_out_counter.process(line_people)
            same_dir_window = max(4.0, float(self.cooldown))
            opp_dir_window = float(self.cooldown)
            for evt in raw_events:
                direction = evt.get("direction")
                if direction not in ("IN", "OUT"):
                    continue
                tid = str(evt["tracking_id"])
                emp_name = name_by_id.get(tid)
                ts = evt.get("timestamp") or time.time()
                prev = self._last_gate_event.get(tid)
                if prev:
                    window = same_dir_window if prev[0] == direction else opp_dir_window
                    if (ts - prev[1]) < window:
                        continue

                if direction == "OUT":
                    is_inside = (
                        (emp_name and emp_name in self._inside_employees)
                        or (tid in self.line_in_counter.inside_tracking_ids)
                        or (self.total_in > self.total_out)
                    )
                    if not is_inside:
                        continue
                    if emp_name:
                        self._inside_employees.discard(emp_name)
                    self.total_out += 1
                elif direction == "IN":
                    if emp_name:
                        self._inside_employees.add(emp_name)
                    self.total_in += 1

                self._last_gate_event[tid] = (direction, ts)
                evt["gate_name"] = self.gate_name
                evt["direction"] = direction
                evt["employee_name"] = emp_name
                evt["event_key"] = f"{self.gate_name}_{tid}_{direction}_{int(ts)}"
                evt["event_timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc)
                events.append(evt)
        else:
            line_people = [
                {**p, "footpoint": p.get("footpoint") or p.get("lower_point")}
                for p in processed_people
            ]
            for evt in self.line_counter.process(line_people):
                direction = evt.get("direction")
                tid = str(evt["tracking_id"])
                emp_name = name_by_id.get(tid)
                ts = evt.get("timestamp") or time.time()

                if direction == "OUT" and getattr(self, "enforce_entry_first", False):
                    is_inside = (
                        (emp_name and emp_name in self._inside_employees)
                        or (tid in getattr(self.line_counter, "inside_tracking_ids", set()))
                        or (self.total_in > self.total_out)
                    )
                    if not is_inside:
                        continue

                if direction == "IN":
                    if emp_name:
                        self._inside_employees.add(emp_name)
                    self.total_in += 1
                elif direction == "OUT":
                    if emp_name:
                        self._inside_employees.discard(emp_name)
                    self.total_out += 1

                evt["gate_name"] = self.gate_name
                evt["direction"] = direction
                evt["employee_name"] = emp_name
                evt["event_key"] = f"{self.gate_name}_{tid}_{direction}_{int(ts)}"
                evt["event_timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc)
                events.append(evt)

        active_ids = [p["id"] for p in processed_people if p.get("id") is not None]
        self.cleanup_tracks(active_ids)
        return events

    def process_in(self, people, frame_shape):
        """
        Channel 1 (IN Camera): Count people walking into the facility.
        Requires >= 28px movement to avoid counting seated desk workers.
        """
        if not self.enabled or not people:
            return []
        now = time.time()
        processed = self.detector.process(people, frame_shape)
        name_by_id = {
            str(p.get("id")): p.get("name")
            for p in people
            if p.get("id") is not None and p.get("name") and p.get("name") != "Unknown"
        }
        events = []
        for p in processed:
            tid = str(p["id"])
            pos = p.get("center") or p.get("footpoint")
            if not pos:
                continue
            emp_name = name_by_id.get(tid)
            st = self._ch1_tracks.get(tid)
            if st is None:
                self._ch1_tracks[tid] = {"first_pos": pos, "frames": 1, "counted": False, "last_seen": now, "name": emp_name}
                continue
            st["frames"] += 1
            st["last_seen"] = now
            if emp_name:
                st["name"] = emp_name
                self._last_in_name = emp_name
            if st["counted"]:
                continue
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
                    "tracking_id": tid, "id": tid, "employee_name": st["name"],
                    "direction": "IN", "gate_name": self.gate_name,
                    "confidence": p.get("confidence"), "timestamp": now,
                    "event_key": f"{self.gate_name}_CH1_{tid}_IN_{int(now)}",
                    "event_timestamp": datetime.fromtimestamp(now, tz=timezone.utc),
                })
        self._ch1_tracks = {k: v for k, v in self._ch1_tracks.items() if now - v["last_seen"] <= 8.0}
        return events

    def process_out(self, people, frame_shape):
        """
        Channel 2 (OUT Camera): Count people walking out of the facility.
        Triggers if same employee from Channel 1 is seen walking on Channel 2.
        """
        if not self.enabled or not people:
            return []
        now = time.time()
        processed = self.detector.process(people, frame_shape)
        name_by_id = {
            str(p.get("id")): p.get("name")
            for p in people
            if p.get("id") is not None and p.get("name") and p.get("name") != "Unknown"
        }
        events = []
        for p in processed:
            tid = str(p["id"])
            pos = p.get("center") or p.get("footpoint")
            if not pos:
                continue
            emp_name = name_by_id.get(tid)
            st = self._ch2_tracks.get(tid)
            if st is None:
                self._ch2_tracks[tid] = {"first_pos": pos, "frames": 1, "counted": False, "last_seen": now, "name": emp_name}
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
                    "tracking_id": tid, "id": tid, "employee_name": resolved_name,
                    "direction": "OUT", "gate_name": self.gate_name,
                    "confidence": p.get("confidence"), "timestamp": now,
                    "event_key": f"{self.gate_name}_CH2_{tid}_OUT_{int(now)}",
                    "event_timestamp": datetime.fromtimestamp(now, tz=timezone.utc),
                })
        self._ch2_tracks = {k: v for k, v in self._ch2_tracks.items() if now - v["last_seen"] <= 8.0}
        return events

    # ----------------------------------------------------------
    # ANNOTATION
    # ----------------------------------------------------------

    def _draw_top_counter_bar(self, frame, camera_label=None):
        """Draw IN/OUT/INSIDE counter bar and virtual gate lines on frame."""
        if not self.enabled or frame is None:
            return frame
        try:
            import cv2
            counts = self.get_counts()
            prefix = f"{self.gate_name} ({camera_label})" if camera_label else self.gate_name
            text = f" {prefix}  |  IN: {counts['total_in']}   OUT: {counts['total_out']}   INSIDE: {counts['current_inside']} "
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(text, font, 0.65, 2)
            bx, by = 16, th + 16
            cv2.rectangle(frame, (bx - 6, by - th - 8), (bx + tw + 6, by + 8), (15, 23, 42), -1)
            cv2.rectangle(frame, (bx - 6, by - th - 8), (bx + tw + 6, by + 8), (54, 210, 185), 2, cv2.LINE_AA)
            cv2.putText(frame, text, (bx, by), font, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            if not self.two_lines and self.line_start and self.line_end:
                cv2.line(frame, tuple(map(int, self.line_start)), tuple(map(int, self.line_end)), (54, 210, 185), 3, cv2.LINE_AA)
            elif self.two_lines and self.line_in_start and self.line_out_start:
                cv2.line(frame, tuple(map(int, self.line_in_start)), tuple(map(int, self.line_in_end)), (34, 197, 94), 3, cv2.LINE_AA)
                cv2.putText(frame, "ENTRY LINE (IN)", (int(self.line_in_start[0]), max(20, int(self.line_in_start[1]) - 8)), font, 0.5, (34, 197, 94), 2, cv2.LINE_AA)
                cv2.line(frame, tuple(map(int, self.line_out_start)), tuple(map(int, self.line_out_end)), (239, 68, 68), 3, cv2.LINE_AA)
                cv2.putText(frame, "EXIT LINE (OUT)", (int(self.line_out_start[0]), min(frame.shape[0] - 10, int(self.line_out_start[1]) + 20)), font, 0.5, (239, 68, 68), 2, cv2.LINE_AA)
        except Exception as exc:
            log.debug("Headcount annotation error: %s", exc)
        return frame

    def annotate(self, frame):
        return self._draw_top_counter_bar(frame)

    def annotate_in(self, frame):
        return self._draw_top_counter_bar(frame, "CH1 - IN")

    def annotate_out(self, frame):
        return self._draw_top_counter_bar(frame, "CH2 - OUT")

    # ----------------------------------------------------------
    # COUNTS + RESET + ENABLE
    # ----------------------------------------------------------

    def get_counts(self):
        return {"gate_name": self.gate_name, "total_in": self.total_in, "total_out": self.total_out, "current_inside": max(0, self.total_in - self.total_out)}

    def cleanup_tracks(self, active_ids):
        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            self.line_in_counter.cleanup_tracks(active_ids)
            self.line_out_counter.cleanup_tracks(active_ids)
        self.line_counter.cleanup_tracks(active_ids)

    def reset_counts(self):
        self.total_in = 0
        self.total_out = 0
        self._last_gate_event.clear()
        if self.two_lines and hasattr(self, "line_in_counter") and hasattr(self, "line_out_counter"):
            self.line_in_counter.reset_counts()
            self.line_out_counter.reset_counts()
        self.line_counter.reset_counts()

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def update_gate_line(self, line_start, line_end, entry_direction="A_TO_B"):
        """Update gate line coordinates at runtime."""
        self.line_start = tuple(line_start)
        self.line_end = tuple(line_end)
        self.entry_direction = entry_direction
        self.line_in_start = (self.line_start[0], max(0, self.line_start[1] - 25))
        self.line_in_end = (self.line_end[0], max(0, self.line_end[1] - 25))
        self.line_out_start = (self.line_start[0], self.line_start[1] + 25)
        self.line_out_end = (self.line_end[0], self.line_end[1] + 25)
        self._init_counters()
