# ============================================================
# FILE: shared/face_recognition/face_quality.py
# PURPOSE: Crops upper-body head regions, upscales small crops, and computes Laplacian blur scores
# USE CASE: Shared Infrastructure (Face Recognition)
# DEBUG TIPS:
#   - Tune face_min_person_height and face_min_blur in shared/config.py for distant CCTV views
# ============================================================

"""Helpers that decide whether a CCTV face observation is good enough to trust."""
import cv2
import numpy as np


def prepare_person_crop(frame, box, head_fraction=0.5, margin=0.1,
                        min_width=240, max_upscale=4.0):
    """
    Crop the head/upper-body region of a tracked person with a margin and
    upscale small crops so the face detector has more pixels to work with.

    Returns (crop, scale). scale > 1 means the crop was enlarged; divide
    measured sizes by it to get sizes in original frame pixels.
    """
    if frame is None or box is None or len(box) != 4:
        return None, 1.0
    frame_h, frame_w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return None, 1.0

    cx1 = max(0, int(x1 - w * margin))
    cx2 = min(frame_w, int(x2 + w * margin))
    cy1 = max(0, int(y1 - h * 0.03))
    cy2 = min(frame_h, int(y1 + h * head_fraction))
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None, 1.0

    scale = 1.0
    if crop.shape[1] < min_width:
        scale = min(float(max_upscale), min_width / crop.shape[1])
        crop = cv2.resize(crop, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)
    return crop, scale


def face_blur_score(image, bbox):
    """
    Sharpness of the face region (variance of the Laplacian). The region is
    resized to a fixed size first so scores are comparable across face sizes.
    Higher is sharper.
    """
    if image is None or bbox is None:
        return 0.0
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return 0.0
    face = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY) if face.ndim == 3 else face
    gray = cv2.resize(gray, (112, 112), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def is_person_big_enough(box, min_height):
    """People far from the camera have faces too small to recognise."""
    if box is None or len(box) != 4:
        return False
    return (box[3] - box[1]) >= min_height
