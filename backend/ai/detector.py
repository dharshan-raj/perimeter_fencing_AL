# ============================================================
# FILE: shared/detection/detector.py
# PURPOSE: YOLOv8 + ByteTrack person detector.
#          Loads the YOLO model once and reuses it every frame.
#          Returns tracked person bounding boxes with IDs.
# USE CASE: All (Shared — called by camera_manager on every frame)
#
# HOW IT WORKS:
#   - Loads YOLOv8n (or model from MODEL_PATH in .env) on first use.
#   - Runs YOLO tracking with ByteTrack algorithm every inference frame.
#   - Only detects class 0 (person) with configurable confidence threshold.
#   - Returns list of person dicts used by all 3 use case modules.
#
# DEBUG TIPS:
#   - "Configured model is missing; using pretrained yolov8n.pt"?
#       → Set MODEL_PATH=yolov8n.pt in .env, or place model at models/yolov8n.pt
#   - Detection confidence too low / too many false positives?
#       → Set PERSON_CONFIDENCE=0.4 (higher = stricter) in .env
#   - ByteTrack IDs resetting every frame?
#       → persist=True must be set (already set). Check YOLO version >= 8.0.
#   - High GPU/CPU usage?
#       → Reduce INFERENCE_FPS in .env (default 3.0).
#       → Use smaller model: yolov8n.pt (fastest).
#   - "YOLO_CONFIG_DIR" warning?
#       → Ultralytics writes settings to config/ dir in project root.
#         This avoids AppData permission issues on Windows.
#   - imgsz=480: smaller resolution speeds up inference with minimal accuracy loss.
#
# OUTPUT FORMAT per person:
#   {
#     "id": int,              # ByteTrack tracking ID (persistent across frames)
#     "confidence": float,    # YOLO detection confidence [0.0–1.0]
#     "box": [x1, y1, x2, y2],  # Bounding box in absolute pixels
#     "point": [cx, y2]       # Bottom-center point (used by IntrusionDetector)
#   }
#
# DEPENDENCIES:
#   - shared/config.py  → settings.model_path, person_confidence, iou_threshold
#   - ultralytics       → YOLO (pip install ultralytics)
# ============================================================

import os
import logging
from pathlib import Path

# Point Ultralytics settings to project config dir (avoids Windows AppData permission issues)
if "YOLO_CONFIG_DIR" not in os.environ:
    os.environ["YOLO_CONFIG_DIR"] = str(Path(__file__).resolve().parent.parent.parent / "config")

from ultralytics import YOLO
from config.settings import settings

log = logging.getLogger(__name__)


class PersonDetector:
    """
    YOLOv8 person detector with ByteTrack multi-object tracking.

    Usage:
        detector = PersonDetector()
        people = detector.detect_track(frame)   # frame is a BGR numpy array
    """

    def __init__(self):
        path = Path(settings.model_path)
        if path.exists():
            self.model = YOLO(str(path))
            log.info("YOLO model loaded from %s", path)
        else:
            log.warning("Configured model %s is missing; using pretrained yolov8n.pt", path)
            self.model = YOLO("yolov8n.pt")

    def detect_track(self, frame):
        """
        Run YOLO detection + ByteTrack tracking on one frame.

        Args:
            frame (np.ndarray): BGR camera frame.

        Returns:
            list[dict]: Person detections with tracking IDs and bounding boxes.

        DEBUG: Returns empty list?
               → Confirm frame is not None and has non-zero shape.
               → Lower PERSON_CONFIDENCE in .env (default 0.30).
               → Check if people are visible in the frame area.
        """
        result = self.model.track(
            frame,
            persist=True,          # ByteTrack: keep track IDs across frames
            classes=[0],           # class 0 = person only
            conf=settings.person_confidence,
            iou=settings.iou_threshold,
            imgsz=480,             # smaller resolution = faster inference
            tracker="bytetrack.yaml",
            verbose=False,
        )[0]

        out = []
        if result.boxes is None:
            return out

        for box in result.boxes:
            if box.id is None:
                continue  # skip untracked detections (ByteTrack not yet assigned ID)
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            out.append({
                "id": int(box.id.item()),
                "confidence": float(box.conf.item()),
                "box": [x1, y1, x2, y2],
                "point": [(x1 + x2) // 2, y2],  # bottom-center for zone checks
            })

        return out
