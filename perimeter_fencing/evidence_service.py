# ============================================================
# FILE: perimeter_fencing/evidence_service.py
# PURPOSE: Saves annotated JPEG evidence snapshots when perimeter intrusion alerts fire
# USE CASE: Perimeter Fencing (Use Case 1)
# DEBUG TIPS:
#   - If snapshots are missing: verify EVIDENCE_DIR in .env and folder write permissions
#   - Evidence files are served via /api/evidence/<relative_path> with admin token
# ============================================================

from datetime import datetime
from pathlib import Path
import cv2
from shared.config import settings
from perimeter_fencing.zone_manager import ZoneManager
def save(frame, person, zone):
    image=frame.copy(); zone.annotate(image); x1,y1,x2,y2=person["box"]; cv2.rectangle(image,(x1,y1),(x2,y2),(0,0,255),2); cv2.putText(image,f"ID {person['id']} {person['confidence']:.2f}",(x1,max(20,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,255),2)
    stamp=datetime.now(); path=Path(settings.evidence_dir)/stamp.strftime("%Y/%m")/"camera_14"; path.mkdir(parents=True,exist_ok=True); file=path/f"intrusion_{stamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"; cv2.imwrite(str(file),image); return str(file.resolve())
