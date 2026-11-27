# ============================================================
# FILE: backend/ai/detector.py
# PURPOSE: YOLO Pose + ByteTrack person detector and leg keypoint extractor.
#          Loads the YOLO Pose model (yolo11n-pose.pt) once and reuses it every frame.
#          Returns tracked person bounding boxes, ByteTrack IDs, and leg keypoints
#          (knees & ankles) in a single pass.
# USE CASE: All (Shared — called by camera_manager on every frame)
#
# HOW IT WORKS:
#   - When POSE_ENABLED=true (default), loads yolo11n-pose.pt (or POSE_MODEL_PATH).
#   - Falls back gracefully to yolov8n.pt if pose weights cannot be loaded offline.
#   - Runs YOLO tracking with ByteTrack (persist=True, class 0 = person).
#   - Extracts COCO leg keypoints:
#       11: left_hip, 12: right_hip,
#       13: left_knee, 14: right_knee,
#       15: left_ankle, 16: right_ankle
#
# DEBUG TIPS:
#   - Pose keypoints empty?
#       -> Ensure POSE_ENABLED=true and models/yolo11n-pose.pt is downloaded.
#       -> Lower POSE_KEYPOINT_CONFIDENCE in .env (default 0.35).
#   - ByteTrack IDs resetting every frame?
#       -> Increase INFERENCE_FPS in .env (recommended >= 8).
# ============================================================

import os
import logging
from pathlib import Path
import cv2

# Point Ultralytics settings to project config dir (avoids Windows AppData permission issues)
if "YOLO_CONFIG_DIR" not in os.environ:
    os.environ["YOLO_CONFIG_DIR"] = str(Path(__file__).resolve().parent.parent.parent / "config")

from ultralytics import YOLO
from config.settings import settings

log = logging.getLogger(__name__)

# COCO 17-keypoint indices for lower body (legs)
LEG_KEYPOINT_INDICES = {
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}

HIP_KEYPOINT_INDICES = {
    "left_hip": 11,
    "right_hip": 12,
}


def draw_leg_pose(image, person, zone=None):
    """
    Draw hip -> knee -> ankle skeleton lines and keypoint dots on the video frame.
    Leg keypoints inside the restricted zone are highlighted in bright RED;
    outside keypoints are drawn in CYAN.
    """
    legs = person.get("leg_keypoints") or {}
    hips = person.get("hip_keypoints") or {}
    if not legs:
        return image

    parts_inside = set(person.get("leg_parts_inside") or [])
    if zone is not None and not parts_inside:
        for name, kp in legs.items():
            if zone.inside((kp[0], kp[1]), image.shape):
                parts_inside.add(name)

    def _pt(d, key):
        v = d.get(key)
        return (int(v[0]), int(v[1])) if v else None

    # Draw leg segments (left & right)
    segments = [
        (_pt(hips, "left_hip"), _pt(legs, "left_knee"), "left_knee"),
        (_pt(legs, "left_knee"), _pt(legs, "left_ankle"), "left_ankle"),
        (_pt(hips, "right_hip"), _pt(legs, "right_knee"), "right_knee"),
        (_pt(legs, "right_knee"), _pt(legs, "right_ankle"), "right_ankle"),
    ]
    for p1, p2, end_name in segments:
        if p1 and p2:
            in_zone = end_name in parts_inside
            color = (0, 0, 255) if in_zone else (255, 220, 0)
            cv2.line(image, p1, p2, color, 3 if in_zone else 2, cv2.LINE_AA)

    # Draw knee & ankle keypoint circles
    for name, kp in legs.items():
        cx, cy = int(kp[0]), int(kp[1])
        in_zone = name in parts_inside
        color = (0, 0, 255) if in_zone else (255, 220, 0)
        radius = 6 if in_zone else 4
        cv2.circle(image, (cx, cy), radius + 1, (15, 23, 42), -1, cv2.LINE_AA)
        cv2.circle(image, (cx, cy), radius, color, -1, cv2.LINE_AA)

    return image


class PersonDetector:
    """
    YOLO Pose + ByteTrack person detector.
    Detects people, assigns persistent ByteTrack IDs, and extracts knee/ankle
    keypoints for leg-level perimeter intrusion detection.
    """

    def __init__(self):
        self.is_pose = False
        if settings.pose_enabled:
            pose_path = Path(settings.pose_model_path)
            if pose_path.exists():
                self.model = YOLO(str(pose_path))
                self.is_pose = True
                log.info("YOLO Pose model loaded from %s", pose_path)
                return
            try:
                # Auto-download yolo11n-pose.pt into models/ if internet is available
                pose_path.parent.mkdir(parents=True, exist_ok=True)
                self.model = YOLO(pose_path.name)
                self.is_pose = True
                log.info("YOLO Pose model loaded: %s", pose_path.name)
                return
            except Exception as exc:
                log.warning(
                    "Could not load pose model %s (%s); falling back to standard person detector",
                    settings.pose_model_path,
                    exc,
                )

        path = Path(settings.model_path)
        if path.exists():
            self.model = YOLO(str(path))
            log.info("YOLO model loaded from %s", path)
        else:
            log.warning("Configured model %s is missing; using pretrained yolov8n.pt", path)
            self.model = YOLO("yolov8n.pt")

    def detect_track(self, frame):
        """
        Run YOLO (+ Pose if enabled) + ByteTrack tracking on one frame.

        Returns list[dict]:
            {
                "id": int,
                "confidence": float,
                "box": [x1, y1, x2, y2],
                "point": [cx, y2],
                "leg_keypoints": {"left_knee": [x, y, conf], ...},
                "hip_keypoints": {"left_hip": [x, y, conf], ...},
            }
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

        kpts_data = None
        if getattr(result, "keypoints", None) is not None and result.keypoints.data is not None:
            kpts_data = result.keypoints.data.cpu().numpy()

        kp_min_conf = float(getattr(settings, "pose_keypoint_confidence", 0.35))

        for idx, box in enumerate(result.boxes):
            if box.id is None:
                continue  # skip untracked detections (ByteTrack not yet assigned ID)

            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            leg_keypoints = {}
            hip_keypoints = {}

            if kpts_data is not None and idx < len(kpts_data):
                person_kpts = kpts_data[idx]
                for name, k_idx in LEG_KEYPOINT_INDICES.items():
                    if k_idx < len(person_kpts):
                        kx, ky, kc = float(person_kpts[k_idx][0]), float(person_kpts[k_idx][1]), float(person_kpts[k_idx][2])
                        if kc >= kp_min_conf and (kx > 0 or ky > 0):
                            leg_keypoints[name] = [int(round(kx)), int(round(ky)), round(kc, 3)]
                for name, k_idx in HIP_KEYPOINT_INDICES.items():
                    if k_idx < len(person_kpts):
                        kx, ky, kc = float(person_kpts[k_idx][0]), float(person_kpts[k_idx][1]), float(person_kpts[k_idx][2])
                        if kc >= kp_min_conf and (kx > 0 or ky > 0):
                            hip_keypoints[name] = [int(round(kx)), int(round(ky)), round(kc, 3)]

            out.append({
                "id": int(box.id.item()),
                "confidence": float(box.conf.item()),
                "box": [x1, y1, x2, y2],
                "point": [(x1 + x2) // 2, y2],  # bottom-center fallback
                "leg_keypoints": leg_keypoints,
                "hip_keypoints": hip_keypoints,
            })

        return out
