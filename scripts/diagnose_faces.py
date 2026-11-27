"""Diagnose face recognition on the live camera (steps 1-4). Run with the venv python."""
import sys, time, os
sys.path.insert(0, os.getcwd())
import cv2
from config.settings import settings
from backend.camera.rtsp_stream import RTSPStream
from backend.ai.detector import PersonDetector
from backend.ai.employee_registry import EmployeeRegistry

N_FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
os.makedirs("scratch_faces", exist_ok=True)

reg = EmployeeRegistry("data/employees")
reg.load_employees(max_photos_per_employee=5)
eng = reg.engine
det = PersonDetector()
stream = RTSPStream(settings.source, settings.source_kind)

stats = dict(frames=0, persons=0, crop_faces=0, crop_single=0, full_faces=0,
             crop_matched=0, full_matched=0)
sims = []
t0 = time.time()
saved = 0
while stats["frames"] < N_FRAMES and time.time() - t0 < 120:
    ok, frame = stream.read()
    if not ok:
        time.sleep(0.2); continue
    stats["frames"] += 1
    people = det.detect_track(frame)
    for p in people:
        stats["persons"] += 1
        x1, y1, x2, y2 = p["box"]
        h = y2 - y1
        crop = frame[max(0, y1):y1 + max(1, int(h * 0.45)), max(0, x1):x2]
        faces = eng.app.get(crop) if crop.size else []
        stats["crop_faces"] += len(faces)
        if len(faces) == 1:
            stats["crop_single"] += 1
        r = reg.recognize_employee(crop) if crop.size else {"status": "NO_CLEAR_FACE"}
        if r["status"] == "MATCHED":
            stats["crop_matched"] += 1
        if r.get("similarity") is not None:
            sims.append((round(r["similarity"], 3), r.get("employee_id"), h, x2 - x1))
        if saved < 10 and crop.size:
            cv2.imwrite(f"scratch_faces/crop_{saved}_h{h}_f{len(faces)}.jpg", crop); saved += 1
    ff = eng.app.get(frame)
    stats["full_faces"] += len(ff)
    for f in ff:
        import numpy as np
        e = f.embedding.astype(np.float32); e /= np.linalg.norm(e)
        best = max(((float(np.dot(e, re)), k) for k, v in reg.employee_embeddings.items() for re in v))
        sims.append(("full", round(best[0], 3), best[1], int(f.bbox[2] - f.bbox[0])))
        if best[0] >= eng.match_threshold:
            stats["full_matched"] += 1
stream.release()
print("STATS", stats)
print("SIMS (score, employee, person_h/face_w, w)", sims[:40])
