# ============================================================
# FILE: shared/face_recognition/train_employee_faces.py
# PURPOSE: Offline utility script to train and inspect employee face embeddings from photos
# USE CASE: Shared Infrastructure (Face Recognition)
# DEBUG TIPS:
#   - Reads employee folders from shared/employee_face/
# ============================================================


from pathlib import Path
import cv2
import numpy as np
import json

from insightface.app import FaceAnalysis


# -------------------------------------------------
# PATHS
# -------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]

EMPLOYEE_DIR = BASE_DIR / "shared" / "employee_face"

OUTPUT_DIR = BASE_DIR / "shared" / "face_recognition"

OUTPUT_FILE = OUTPUT_DIR / "employee_embeddings.npz"

LABEL_FILE = OUTPUT_DIR / "employee_labels.json"


# -------------------------------------------------
# LOAD INSIGHTFACE MODEL
# -------------------------------------------------

print("Loading InsightFace model...")

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(
    ctx_id=-1,
    det_size=(640, 640)
)

print("InsightFace model loaded!")


# -------------------------------------------------
# PROCESS EMPLOYEE PHOTOS
# -------------------------------------------------

all_embeddings = []
all_labels = []

if not EMPLOYEE_DIR.exists():
    raise FileNotFoundError(
        f"Employee folder not found: {EMPLOYEE_DIR}"
    )

employee_folders = [
    folder for folder in EMPLOYEE_DIR.iterdir()
    if folder.is_dir()
]

if not employee_folders:
    raise RuntimeError(
        "No employee ID folders found inside employee_face."
    )

for employee_folder in employee_folders:

    employee_id = employee_folder.name

    print(f"\nProcessing employee: {employee_id}")

    image_files = [
        path for path in employee_folder.iterdir()
        if path.suffix.lower() in
        [".jpg", ".jpeg", ".png", ".bmp"]
    ]

    valid_count = 0

    for image_path in image_files:

        image = cv2.imread(str(image_path))

        if image is None:
            print(f"Could not read: {image_path.name}")
            continue

        faces = app.get(image)

        if len(faces) != 1:
            print(
                f"Skipping {image_path.name}: "
                f"expected one face, found {len(faces)}"
            )
            continue

        embedding = faces[0].normed_embedding

        if embedding is None:
            print(f"No embedding: {image_path.name}")
            continue

        all_embeddings.append(
            np.asarray(embedding, dtype=np.float32)
        )

        all_labels.append(employee_id)

        valid_count += 1

        print(f"Processed: {image_path.name}")

    print(
        f"Valid photos for {employee_id}: {valid_count}"
    )

if not all_embeddings:
    raise RuntimeError(
        "No valid face embeddings created. "
        "Check your photos and employee folders."
    )


# -------------------------------------------------
# SAVE RECOGNITION DATA
# -------------------------------------------------

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

np.savez_compressed(
    OUTPUT_FILE,
    embeddings=np.stack(all_embeddings),
    labels=np.asarray(all_labels)
)

with open(LABEL_FILE, "w", encoding="utf-8") as file:
    json.dump(
        {
            "employee_ids": sorted(set(all_labels)),
            "total_photos": len(all_labels)
        },
        file,
        indent=4
    )

print("\n================================")
print("EMPLOYEE FACE DATA CREATED")
print("================================")

print("Total valid photos:", len(all_embeddings))
print("Total employees:", len(set(all_labels)))
print("Embedding file:", OUTPUT_FILE)
print("Labels file:", LABEL_FILE)
