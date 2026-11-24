
"""
Headcount Detector
------------------

Processes existing YOLOv8 + ByteTrack person detections
for Plant Entrance Gate 3.

This module does NOT initialize another YOLO model.
It reuses detections from the existing CameraManager.
"""

import logging

from typing import Any


logger = logging.getLogger(__name__)


class HeadcountDetector:

    def __init__(self, confidence_threshold: float = 0.35):

        self.confidence_threshold = confidence_threshold

        logger.info(
            "Gate 3 Headcount Detector initialized"
        )

    # =====================================================
    # PROCESS EXISTING PERSON DETECTIONS
    # =====================================================

    def process(
        self,
        people: list[dict],
        frame_shape: tuple
    ) -> list[dict]:

        """
        Validate and prepare existing tracked people
        for Gate 3 directional counting.

        Args:
            people:
                YOLOv8 + ByteTrack detection results.

            frame_shape:
                Current camera frame dimensions.

        Returns:
            List of normalized person detection records.
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

                confidence = float(
                    person.get("confidence", 0)
                )

                box = person.get("box")

                # -----------------------------------------
                # Validate tracking ID
                # -----------------------------------------

                if tracking_id is None:
                    continue

                # -----------------------------------------
                # Confidence filtering
                # -----------------------------------------

                if confidence < self.confidence_threshold:
                    continue

                # -----------------------------------------
                # Validate bounding box
                # -----------------------------------------

                if not box or len(box) != 4:
                    continue

                x1, y1, x2, y2 = map(int, box)

                if x2 <= x1 or y2 <= y1:
                    continue

                # -----------------------------------------
                # Keep coordinates within frame
                # -----------------------------------------

                x1 = max(0, min(x1, frame_width - 1))
                y1 = max(0, min(y1, frame_height - 1))

                x2 = max(0, min(x2, frame_width - 1))
                y2 = max(0, min(y2, frame_height - 1))

                if x2 <= x1 or y2 <= y1:
                    continue

                # -----------------------------------------
                # Calculate person footpoint
                # -----------------------------------------

                center_x = int((x1 + x2) / 2)

                bottom_y = y2

                footpoint = (
                    center_x,
                    bottom_y
                )

                lower_point = (
                    center_x,
                    int(y1 + 0.75 * (y2 - y1))
                )

                # -----------------------------------------
                # Prepare normalized detection
                # -----------------------------------------

                processed_people.append({

                    "id": str(tracking_id),

                    "confidence": confidence,

                    "box": (
                        x1,
                        y1,
                        x2,
                        y2
                    ),

                    "footpoint": footpoint,

                    "lower_point": lower_point,

                    "center": (
                        center_x,
                        int((y1 + y2) / 2)
                    ),

                    "frame_width": frame_width,

                    "frame_height": frame_height

                })

            except (TypeError, ValueError, KeyError):
                logger.warning(
                    "Invalid person detection skipped"
                )

                continue

        return processed_people

    # =====================================================
    # GET PERSON FOOTPOINT
    # =====================================================

    @staticmethod
    def get_footpoint(person: dict) -> tuple[int, int] | None:

        """
        Return the bottom-center point of a person's
        bounding box.

        This point is useful for determining whether
        a person crossed the Gate 3 counting line.
        """

        footpoint = person.get("footpoint")

        if footpoint:
            return tuple(footpoint)

        box = person.get("box")

        if not box or len(box) != 4:
            return None

        x1, y1, x2, y2 = box

        return (
            int((x1 + x2) / 2),
            int(y2)
        )
