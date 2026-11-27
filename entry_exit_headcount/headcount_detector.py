# ============================================================
# FILE: entry_exit_headcount/headcount_detector.py
# PURPOSE: Validates and normalizes existing YOLO + ByteTrack
#          person detections for Gate 3 directional counting.
#          Does NOT run a second YOLO model — reuses detections
#          already produced by shared/detection/detector.py.
# USE CASE: Entry/Exit Headcount (Use Case 2)
#
# HOW IT WORKS:
#   - Receives a list of raw person dicts from CameraManager.
#   - Filters out low-confidence or invalid detections.
#   - Computes footpoint (bottom-center) and lower_point (75% down)
#     used by LineCounter for crossing detection.
#
# DEBUG TIPS:
#   - Headcount always 0?
#       → Confirm people list is non-empty (check camera_manager.people).
#       → Confidence threshold default is 0.35 — lower if no detections pass.
#   - Person footpoint wrong?
#       → lower_point = y1 + 0.75*(y2-y1). Check box coords are in px.
#   - Unexpected skipped detections?
#       → Look for "Invalid person detection skipped" in logs (WARNING level).
#   - Frame shape error?
#       → Must be (height, width, channels) — raw OpenCV BGR frame.
#
# OUTPUT FORMAT per person:
#   {
#     "id": str,          "confidence": float,
#     "box": (x1,y1,x2,y2),
#     "footpoint": (cx, y2),
#     "lower_point": (cx, y1 + 0.75*(y2-y1)),
#     "center": (cx, cy),
#     "frame_width": int, "frame_height": int
#   }
#
# DEPENDENCIES:
#   - Called by: entry_exit_headcount/headcount_manager.py
# ============================================================

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HeadcountDetector:
    """
    Validates and prepares raw YOLO detections for Gate 3 line counting.
    Does NOT instantiate a new YOLO model.
    """

    def __init__(self, confidence_threshold: float = 0.35):
        self.confidence_threshold = confidence_threshold
        logger.info("Gate 3 Headcount Detector initialized (threshold=%.2f)", confidence_threshold)

    def process(self, people: list[dict], frame_shape: tuple) -> list[dict]:
        """
        Validate and normalize detected people for the counting pipeline.

        Args:
            people      : Raw YOLO+ByteTrack detections from CameraManager.
            frame_shape : (height, width, channels) of the current frame.

        Returns:
            List of normalized person dicts with footpoint & lower_point.

        DEBUG: Empty return list?
               → Check people input is not empty.
               → Check confidence_threshold vs actual detections.
               → Ensure frame_shape is a valid 2D+ tuple.
        """
        if not people or len(frame_shape) < 2:
            return []

        frame_height, frame_width = frame_shape[:2]
        if frame_width <= 0 or frame_height <= 0:
            return []

        processed_people = []

        for person in people:
            try:
                tracking_id = person.get("id")
                confidence = float(person.get("confidence", 0))
                box = person.get("box")

                # Skip detections without a tracking ID
                if tracking_id is None:
                    continue

                # Skip low-confidence detections
                if confidence < self.confidence_threshold:
                    continue

                # Skip invalid bounding boxes
                if not box or len(box) != 4:
                    continue

                x1, y1, x2, y2 = map(int, box)
                if x2 <= x1 or y2 <= y1:
                    continue

                # Clamp coordinates to frame boundaries
                x1 = max(0, min(x1, frame_width - 1))
                y1 = max(0, min(y1, frame_height - 1))
                x2 = max(0, min(x2, frame_width - 1))
                y2 = max(0, min(y2, frame_height - 1))

                if x2 <= x1 or y2 <= y1:
                    continue

                center_x = int((x1 + x2) / 2)

                # footpoint = bottom-center of bounding box
                footpoint = (center_x, y2)

                # lower_point = 75% down the box — avoids upper doorway line issues
                lower_point = (center_x, int(y1 + 0.75 * (y2 - y1)))

                processed_people.append({
                    "id": str(tracking_id),
                    "confidence": confidence,
                    "box": (x1, y1, x2, y2),
                    "footpoint": footpoint,
                    "lower_point": lower_point,
                    "center": (center_x, int((y1 + y2) / 2)),
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                })

            except (TypeError, ValueError, KeyError):
                logger.warning("Invalid person detection skipped")
                continue

        return processed_people

    @staticmethod
    def get_footpoint(person: dict) -> tuple[int, int] | None:
        """
        Return bottom-center of a person's bounding box.
        Falls back to computing from box if footpoint not pre-calculated.

        DEBUG: Returns None if box is missing or malformed.
        """
        footpoint = person.get("footpoint")
        if footpoint:
            return tuple(footpoint)
        box = person.get("box")
        if not box or len(box) != 4:
            return None
        x1, y1, x2, y2 = box
        return (int((x1 + x2) / 2), int(y2))
