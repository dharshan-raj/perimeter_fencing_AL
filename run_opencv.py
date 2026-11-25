"""
IT Furnace AI - Standalone OpenCV Live Display
Runs YOLO person detection, ByteTrack tracking, InsightFace employee recognition,
and strict single-line IN/OUT headcount directly in an OpenCV desktop window.

Press 'q' or 'ESC' in the window to quit.
Press 'r' to reset inside headcount counts.
"""

import sys
import time
import cv2
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

# Setup paths and environment
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.database import Base, engine, SessionLocal
from backend import models
from backend.camera.camera_manager import camera_manager


def init_database():
    """Ensure database tables exist before camera starts."""
    Base.metadata.create_all(bind=engine)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(headcount_events)"))
            cols = [r[1] for r in res.fetchall()]
            if "employee_name" not in cols and "id" in cols:
                conn.execute(text("ALTER TABLE headcount_events ADD COLUMN employee_name VARCHAR(100)"))
    except Exception:
        pass


def draw_hud(frame, counts, total_detected, auth_count, unk_count, is_perimeter_intrusion=False):
    """Draw top header HUD banner with IN/OUT/INSIDE, live authorization, and perimeter status."""
    h, w = frame.shape[:2]
    hud_h = 56

    # Semi-transparent dark background for HUD
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, hud_h), (15, 23, 42), -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    cv2.line(frame, (0, hud_h), (w, hud_h), (54, 210, 185), 2)

    font = cv2.FONT_HERSHEY_SIMPLEX

    # Left: Camera info & Perimeter status
    cam_text = f"{settings.camera_name} - {settings.camera_location}"
    cv2.putText(frame, cam_text, (16, 26), font, 0.60, (255, 255, 255), 2, cv2.LINE_AA)

    # Perimeter status pill
    perim_status = "PERIMETER: BREACH / INTRUSION!" if is_perimeter_intrusion else "PERIMETER: SECURE"
    perim_color = (0, 0, 255) if is_perimeter_intrusion else (34, 197, 94)
    cv2.putText(frame, perim_status, (16, 48), font, 0.50, perim_color, 2, cv2.LINE_AA)

    # Center: Counts Badge
    center_text = f"IN: {counts['total_in']}   |   OUT: {counts['total_out']}   |   CURRENTLY INSIDE: {counts['current_inside']}"
    (tw, _), _ = cv2.getTextSize(center_text, font, 0.65, 2)
    cx = max(280, (w - tw) // 2)
    cv2.putText(frame, center_text, (cx, 34), font, 0.65, (54, 210, 185), 2, cv2.LINE_AA)

    # Right: Live detection stats
    stats_text = f"Detected: {total_detected}  (Auth: {auth_count} | Unk: {unk_count})"
    (stw, _), _ = cv2.getTextSize(stats_text, font, 0.55, 1)
    rx = max(cx + tw + 20, w - stw - 16)
    cv2.putText(frame, stats_text, (rx, 34), font, 0.55, (203, 213, 225), 1, cv2.LINE_AA)


def draw_footer(frame):
    """Draw bottom help line."""
    h, w = frame.shape[:2]
    footer_h = 30
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - footer_h), (w, h), (15, 23, 42), -1)
    cv2.addWeighted(overlay, 0.80, frame, 0.20, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX
    help_text = "[Q / ESC] Quit   |   [R] Reset Inside Count   |   Green = Authorised   Yellow = Unknown   Red = Unauthorised"
    cv2.putText(frame, help_text, (16, h - 9), font, 0.45, (148, 163, 184), 1, cv2.LINE_AA)


def main():
    print("=" * 65)
    print(" IT FURNACE AI - STANDALONE OPENCV LIVE MONITOR")
    print("=" * 65)
    print(f" Camera Source: {settings.source}")
    print(" Starting AI Vision Pipeline (YOLOv8 + ByteTrack + InsightFace)...")

    # 1. Initialize DB and start Camera Manager
    init_database()
    camera_manager.start()

    window_name = "IT Furnace AI - Live Person & Headcount Monitor"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    print("\nWaiting for camera frames...")
    last_print = time.time()
    prev_in = 0
    prev_out = 0
    latest_banner = ""
    latest_banner_time = 0.0

    try:
        while True:
            frame = camera_manager.last_frame
            if frame is None:
                # Still connecting to RTSP
                waiting_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(
                    waiting_frame,
                    f"Connecting to RTSP Camera: {settings.camera_name}...",
                    (340, 360),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (54, 210, 185),
                    2,
                    cv2.LINE_AA
                )
                cv2.putText(
                    waiting_frame,
                    f"Status: {camera_manager.status} (Attempt {camera_manager.reconnect_attempt})",
                    (420, 410),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (148, 163, 184),
                    1,
                    cv2.LINE_AA
                )
                cv2.imshow(window_name, waiting_frame)
                key = cv2.waitKey(100) & 0xFF
                if key in (ord('q'), ord('Q'), 27):
                    break
                continue

            display_frame = frame.copy()

            # 2. Check for Perimeter Zone Intrusion
            people = camera_manager.people or []
            is_perimeter_intrusion = False
            for p in people:
                pt = p.get("point")
                if not pt:
                    bx = p["box"]
                    pt = ((bx[0] + bx[2]) / 2, bx[3])
                if camera_manager.zone.inside(pt, display_frame.shape):
                    is_perimeter_intrusion = True
                    p["in_perimeter"] = True
                else:
                    p["in_perimeter"] = False

            # 3. Draw Perimeter Zone on frame (Glowing boundary + semi-transparent fill)
            camera_manager.zone.annotate(display_frame, is_intrusion=is_perimeter_intrusion)

            # 4. Draw Counting Lines & Gates
            if camera_manager.in_thread and camera_manager.in_thread.is_alive():
                camera_manager.headcount.annotate_out(display_frame)
            else:
                camera_manager.headcount.annotate(display_frame)

            # Retrieve inside tracking IDs and names
            inside_emps = getattr(camera_manager.headcount, "_inside_employees", set())
            inside_tids = (
                getattr(camera_manager.headcount.line_in_counter, "inside_tracking_ids", set())
                if hasattr(camera_manager.headcount, "line_in_counter")
                else getattr(camera_manager.headcount.line_counter, "inside_tracking_ids", set())
            )

            # 5. Annotate Each Detected Person
            auth_count = 0
            unk_count = 0

            for person in people:
                x1, y1, x2, y2 = person["box"]
                p_name = person.get("name")
                tid = str(person["id"])

                # Check cache fallback if not on current frame
                if (not p_name or p_name == "Unknown") and hasattr(camera_manager, "_face_cache"):
                    cached_entry = camera_manager._face_cache.get(person["id"])
                    if cached_entry and cached_entry[0] and cached_entry[0] != "Unknown":
                        p_name = cached_entry[0]

                # Authorised check
                is_authorised = bool(p_name and p_name != "Unknown")
                is_in_perimeter = person.get("in_perimeter", False)

                if is_in_perimeter:
                    auth_label = "PERIMETER INTRUDER"
                    box_color = (0, 0, 255)  # Bright Red for intrusion
                elif is_authorised:
                    auth_count += 1
                    auth_label = "AUTHORISED"
                    box_color = (34, 197, 94)  # Vibrant Green
                else:
                    unk_count += 1
                    auth_label = "UNKNOWN"
                    box_color = (0, 215, 255)  # Amber / Yellow

                # Determine IN / OUT state
                is_p_inside = (p_name and p_name in inside_emps) or (tid in inside_tids)
                dir_text = "IN" if is_p_inside else "OUT"

                disp_name = p_name.capitalize() if is_authorised else f"ID {tid}"
                conf = person.get("confidence", 0.0)
                label_text = f"{disp_name} [{auth_label}] - {dir_text} ({conf:.2f})"

                # Draw bounding box
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)

                # Draw label badge with background
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.52
                thickness = 2
                (tw, th), baseline = cv2.getTextSize(label_text, font, scale, thickness)
                badge_y1 = max(0, y1 - th - 8)
                badge_y2 = y1
                badge_x1 = x1
                badge_x2 = min(display_frame.shape[1], x1 + tw + 8)

                # Solid dark label background
                cv2.rectangle(display_frame, (badge_x1, badge_y1), (badge_x2, badge_y2), (15, 23, 42), -1)
                cv2.rectangle(display_frame, (badge_x1, badge_y1), (badge_x2, badge_y2), box_color, 1)
                cv2.putText(
                    display_frame,
                    label_text,
                    (badge_x1 + 4, badge_y2 - 5),
                    font,
                    scale,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA
                )

            # 4. Draw HUD Header & Footer
            counts = camera_manager.headcount.get_counts()
            draw_hud(display_frame, counts, len(people), auth_count, unk_count, is_perimeter_intrusion)

            # Check for new crossing event
            cur_in = counts['total_in']
            cur_out = counts['total_out']
            if cur_in > prev_in or cur_out > prev_out:
                evt_type = "IN" if cur_in > prev_in else "OUT"
                latest_banner = f"CROSSING EVENT: {evt_type} (Total In: {cur_in} | Total Out: {cur_out})"
                latest_banner_time = time.time()
                print(f"\n>>> [CROSSING EVENT DETECTED] Direction: {evt_type} | Total In: {cur_in} | Total Out: {cur_out} | Inside: {counts['current_inside']}")
                prev_in = cur_in
                prev_out = cur_out

            # Display crossing popup banner if recent (within 3 seconds)
            if time.time() - latest_banner_time < 3.0 and latest_banner:
                (bw, bh), _ = cv2.getTextSize(latest_banner, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
                bx = max(10, (display_frame.shape[1] - bw) // 2)
                by = display_frame.shape[0] - 60
                cv2.rectangle(display_frame, (bx - 12, by - bh - 10), (bx + bw + 12, by + 10), (15, 23, 42), -1)
                cv2.rectangle(display_frame, (bx - 12, by - bh - 10), (bx + bw + 12, by + 10), (34, 197, 94), 2)
                cv2.putText(display_frame, latest_banner, (bx, by), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)

            draw_footer(display_frame)

            # 5. Display frame in OpenCV window
            cv2.imshow(window_name, display_frame)

            # 6. Handle keyboard input
            key = cv2.waitKey(20) & 0xFF
            if key in (ord('q'), ord('Q'), 27):  # 'q' or ESC
                print("\nExiting monitor...")
                break
            elif key in (ord('r'), ord('R')):
                # Reset counts
                if hasattr(camera_manager.headcount, "_inside_employees"):
                    camera_manager.headcount._inside_employees.clear()
                if hasattr(camera_manager.headcount, "line_counter"):
                    camera_manager.headcount.line_counter.reset()
                print("\n[INFO] Inside count reset!")

            # Periodic console log
            if time.time() - last_print > 5.0:
                print(f"[STATUS] {datetime.now().strftime('%H:%M:%S')} | Total In: {counts['total_in']} | Total Out: {counts['total_out']} | Inside: {counts['current_inside']} | Detected: {len(people)} (Auth: {auth_count})")
                last_print = time.time()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        camera_manager.stop()
        cv2.destroyAllWindows()
        print("Live monitor stopped.")


if __name__ == "__main__":
    main()
