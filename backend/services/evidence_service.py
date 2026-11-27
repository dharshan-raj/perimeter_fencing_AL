# ============================================================
# FILE: perimeter_fencing/evidence_service.py
# PURPOSE: Saves a JPEG evidence snapshot whenever an intrusion
#          alert fires. Annotates the frame with zone overlay
#          and person bounding box before writing to disk.
# USE CASE: Perimeter Fencing (Use Case 1)
#
# HOW IT WORKS:
#   - Called by camera_manager._run() after an intrusion event.
#   - Copies the current frame, draws zone + person box on it.
#   - Saves to: evidence/YYYY/MM/camera_14/<timestamp>.jpg
#   - Returns the absolute file path string for DB storage.
#
# DEBUG TIPS:
#   - Evidence images not being saved?
#       → Check EVIDENCE_DIR in .env (default: "evidence")
#       → Confirm the process has write permission to that directory.
#       → Look for OSError in logs: "Could not write evidence image"
#   - Evidence directory path wrong?
#       → settings.evidence_dir is set in shared/config.py from .env
#   - Image is black or corrupted?
#       → Confirm frame passed is a valid BGR numpy array (not None).
#   - Bounding box missing on saved image?
#       → person["box"] must be [x1, y1, x2, y2] in pixel coords.
#
# OUTPUT PATH FORMAT:
#   evidence/2026/11/camera_14/intrusion_20261125_155413_242964.jpg
#
# DEPENDENCIES:
#   - shared/config.py                   → settings.evidence_dir
#   - perimeter_fencing/zone_manager.py  → ZoneManager.annotate()
#   - cv2 (OpenCV)                       → rectangle, putText, imwrite
# ============================================================

from datetime import datetime
from pathlib import Path
import cv2

from config.settings import settings
from backend.use_cases.perimeter.zone_manager import ZoneManager


def save(frame, person, zone):
    """
    Save an annotated evidence image for a perimeter intrusion event.

    Args:
        frame  (np.ndarray): Raw camera frame at the moment of intrusion.
        person (dict):       {"id", "box": [x1,y1,x2,y2], "confidence"}
        zone   (ZoneManager): Active zone manager to draw polygon overlay.

    Returns:
        str: Absolute path of the saved JPEG file.

    DEBUG: If this returns a path but file is missing on disk:
           → Check disk space and directory permissions.
           → cv2.imwrite returns False on failure; add logging if needed.
    """
    image = frame.copy()

    # Draw the perimeter zone overlay (polygon + label)
    zone.annotate(image)

    # Draw the intruding person's bounding box + ID label
    x1, y1, x2, y2 = person["box"]
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.putText(
        image,
        f"ID {person['id']} {person['confidence']:.2f}",
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 255),
        2,
    )

    # Build timestamped output path: evidence/YYYY/MM/camera_14/
    stamp = datetime.now()
    path = (
        Path(settings.evidence_dir)
        / stamp.strftime("%Y/%m")
        / "camera_14"
    )
    path.mkdir(parents=True, exist_ok=True)

    file = path / f"intrusion_{stamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    cv2.imwrite(str(file), image)

    return str(file.resolve())
