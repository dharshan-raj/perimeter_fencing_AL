"""Offline face diagnostic on saved CCTV evidence frames (camera unreachable)."""
import sys, os, glob
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
from ultralytics import YOLO
from backend.face_recognition.employee_registry import EmployeeRegistry

files = sorted(glob.glob("evidence/**/*.jpg", recursive=True))
step = max(1, len(files) // int(sys.argv[1]))
files = files[::step][: int(sys.argv[1])]
reg = EmployeeRegistry("backend/employee_face"); reg.load_employees(5)
eng = reg.engine
yolo = YOLO("models/yolov8n.pt") if os.path.exists("models/yolov8n.pt") else YOLO("yolov8n.pt")
os.makedirs("scratch_faces", exist_ok=True)
S = dict(images=0, persons=0, crop_faces=0, crop_single=0, crop_matched=0,
         pad_faces=0, pad_matched=0, full_faces=0, full_matched=0)
rows = []
def best_match(face):
    e = face.embedding.astype(np.float32); e /= np.linalg.norm(e)
    return max((float(np.dot(e, r)), k) for k, v in reg.employee_embeddings.items() for r in v)
for f in files:
    img = cv2.imread(f)
    if img is None: continue
    S["images"] += 1
    for b in yolo(img, classes=[0], conf=0.45, verbose=False)[0].boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0].tolist()); h = y2 - y1; w = x2 - x1
        S["persons"] += 1
        crop = img[max(0, y1):y1 + int(h * .45), max(0, x1):x2]
        fs = eng.app.get(crop) if crop.size else []
        S["crop_faces"] += len(fs); S["crop_single"] += len(fs) == 1
        r = reg.recognize_employee(crop) if crop.size else {"status": "NO_CLEAR_FACE"}
        S["crop_matched"] += r["status"] == "MATCHED"
        # padded whole-person crop (+20% margin), pick best face
        pad = img[max(0, y1 - int(h * .1)):y2 + int(h * .1), max(0, x1 - int(w * .2)):x2 + int(w * .2)]
        pf = eng.app.get(pad) if pad.size else []
        S["pad_faces"] += len(pf)
        if pf:
            m = max(best_match(x) for x in pf)
            S["pad_matched"] += m[0] >= eng.match_threshold
            rows.append(("pad", round(m[0], 3), m[1], h))
        rows.append(("crop", r["status"], None if r.get("similarity") is None else round(r["similarity"], 3), h))
    for fc in eng.app.get(img):
        S["full_faces"] += 1
        m = best_match(fc); S["full_matched"] += m[0] >= eng.match_threshold
        rows.append(("full", round(m[0], 3), m[1], int(fc.bbox[2] - fc.bbox[0])))
print("STATS", S)
print("ROWS", rows[:60])
