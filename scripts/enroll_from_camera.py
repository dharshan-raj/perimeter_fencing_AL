"""
Enrol an employee from the REAL CCTV camera (camera-quality photos match far better
than phone photos).

  python scripts/enroll_from_camera.py --name dharshan --frames 20 --interval 1.5
  python scripts/enroll_from_camera.py --name dharshan --from-dir C:/path/to/cctv_snapshots

Ask the employee to walk toward the camera while it runs. Only ONE person should be in
frame. Saved face crops go to shared/employee_face/<name>/cam_*.jpg and are picked up
automatically next start (the embedding cache refreshes itself when photos change).
"""
import argparse, os, sys, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
import cv2
from insightface.app import FaceAnalysis

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--frames", type=int, default=20)
ap.add_argument("--interval", type=float, default=1.5)
ap.add_argument("--from-dir")
ap.add_argument("--min-face", type=int, default=45, help="minimum face width in pixels")
args = ap.parse_args()

out = Path("shared/employee_face") / args.name.lower()
out.mkdir(parents=True, exist_ok=True)
app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(640, 640))
saved = 0


def try_save(frame):
    """Save a padded face crop if the frame holds exactly one decent face."""
    global saved
    faces = [f for f in app.get(frame) if f.det_score >= 0.6]
    if len(faces) != 1:
        return False
    x1, y1, x2, y2 = faces[0].bbox
    w, h = x2 - x1, y2 - y1
    if w < args.min_face:
        return False
    pad_x, pad_y = int(w * 0.6), int(h * 0.6)
    H, W = frame.shape[:2]
    crop = frame[max(0, int(y1) - pad_y):min(H, int(y2) + pad_y),
                 max(0, int(x1) - pad_x):min(W, int(x2) + pad_x)]
    if len(app.get(crop)) != 1:
        return False
    cv2.imwrite(str(out / f"cam_{int(time.time() * 1000)}.jpg"), crop)
    saved += 1
    return True


if args.from_dir:
    for f in sorted(Path(args.from_dir).glob("*")):
        img = cv2.imread(str(f))
        if img is not None:
            try_save(img)
else:
    from shared.config import settings
    from shared.camera.rtsp_stream import RTSPStream
    stream = RTSPStream(settings.source, settings.source_kind)
    deadline = time.time() + 180
    last = 0.0
    while saved < args.frames and time.time() < deadline:
        ok, frame = stream.read()
        if ok and time.time() - last >= args.interval:
            last = time.time()
            if try_save(frame):
                print(f"saved {saved}/{args.frames}")
    stream.release()

print(f"Enrolled {saved} camera photo(s) for {args.name} in {out}")
