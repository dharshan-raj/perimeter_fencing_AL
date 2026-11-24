"""
Measure face recognition accuracy on labelled images.

Layout:  <root>/<employee_or_unknown>/*.jpg   (folder name = ground truth;
         use a folder named "unknown" for people who are NOT employees)

  python scripts/evaluate_recognition.py --root backend/employee_face --skip 15 --limit 20
      -> evaluates photos NOT used for enrolment (skips the first 15 per person)

  python scripts/evaluate_recognition.py --root eval_frames --yolo
      -> labelled CCTV frames: detects the person first, then recognises the head crop
"""
import argparse, os, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.getcwd())
import cv2
from backend.config import settings
from backend.face_recognition.employee_registry import EmployeeRegistry
from backend.face_recognition.face_quality import prepare_person_crop, face_blur_score

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--skip", type=int, default=0)
ap.add_argument("--limit", type=int, default=20)
ap.add_argument("--yolo", action="store_true")
ap.add_argument("--threshold", type=float, default=settings.face_match_threshold)
ap.add_argument("--margin", type=float, default=settings.face_match_margin)
args = ap.parse_args()

reg = EmployeeRegistry("backend/employee_face")
reg.load_employees(max_photos_per_employee=settings.face_max_photos)
eng = reg.engine
yolo = None
if args.yolo:
    from ultralytics import YOLO
    yolo = YOLO("models/yolov8n.pt" if os.path.exists("models/yolov8n.pt") else "yolov8n.pt")

v1, v2 = Counter(), Counter()
confusions = Counter()

for folder in sorted(p for p in Path(args.root).iterdir() if p.is_dir()):
    truth = folder.name.lower()
    files = sorted(f for f in folder.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"})
    for f in files[args.skip: args.skip + args.limit]:
        img = cv2.imread(str(f))
        if img is None:
            continue
        crops = [img]
        if yolo is not None:
            crops = []
            for b in yolo(img, classes=[0], conf=0.45, verbose=False)[0].boxes:
                c, _ = prepare_person_crop(img, list(map(int, b.xyxy[0].tolist())))
                if c is not None:
                    crops.append(c)
        for crop in crops:
            # v1: old single best photo, fixed 0.45, exactly one face
            r1 = eng.recognize(crop, reg.employee_embeddings)
            n1 = r1["employee_id"] if r1["status"] == "MATCHED" else r1["status"]
            # v2: largest face + top-k mean + margin
            found = eng.embed_best_face(crop, settings.face_min_det_score)
            if found is None:
                n2 = "NO_FACE"
            else:
                r2 = eng.match_embedding(found["embedding"], reg.employee_embeddings,
                                         threshold=args.threshold, margin=args.margin)
                n2 = r2["employee_id"] if r2["status"] == "MATCHED" else r2["status"]
            for counter, got in ((v1, n1), (v2, n2)):
                if got == truth:
                    counter["correct"] += 1
                elif got in ("NO_CLEAR_FACE", "NO_FACE"):
                    counter["no_face"] += 1
                elif got in ("UNKNOWN", "AMBIGUOUS"):
                    counter["not_matched_" + got.lower()] += 1
                else:
                    counter["WRONG_PERSON" if truth != "unknown" else "FALSE_ACCEPT"] += 1
                    confusions[(truth, got)] += 1
            if truth == "unknown" and n2 not in ("UNKNOWN", "AMBIGUOUS", "NO_FACE"):
                pass

print("v1 (old):", dict(v1))
print("v2 (new):", dict(v2))
print("wrong-person pairs (truth, predicted):", dict(confusions))
