# ============================================================
# FILE: shared/face_recognition/employee_registry.py
# PURPOSE: Loads enrolled employee folders from shared/employee_face/ and matches query face crops
# USE CASE: Shared Infrastructure (Face Recognition)
# DEBUG TIPS:
#   - Place employee face photos under shared/employee_face/<employee_name>/*.jpg
#   - If 0 employees load: check folder path and InsightFace model permissions
# ============================================================


from pathlib import Path
import cv2

from .insightface_engine import InsightFaceEngine
from . import embedding_cache


class EmployeeRegistry:
    def __init__(self, photos_dir="shared/employee_face"):
        p = Path(photos_dir)
        if not p.exists():
            for alt in ["shared/employee_face", "employee_faces", "employee_face"]:
                if Path(alt).exists():
                    p = Path(alt)
                    break
        self.photos_dir = p
        self.engine = InsightFaceEngine()
        self.employee_embeddings = {}

    def load_employees(self, max_photos_per_employee=5, use_cache=True):
        if not self.photos_dir.exists():
            raise FileNotFoundError(
                f"Employee photo folder not found: {self.photos_dir}"
            )

        # Fast path: reuse embeddings from disk if no photo changed.
        cache_path = self.photos_dir / embedding_cache.CACHE_NAME
        signature = embedding_cache.photos_signature(
            self.photos_dir, max_photos_per_employee
        )
        if use_cache:
            cached = embedding_cache.load_cache(cache_path, signature)
            if cached:
                self.employee_embeddings = cached
                for employee_id, vectors in cached.items():
                    print(f"Loaded {employee_id}: {len(vectors)} photo(s) (cache)")
                return self.employee_embeddings

        self.employee_embeddings.clear()

        for employee_id, image_paths in embedding_cache.list_employee_photos(
            self.photos_dir
        ).items():
            embeddings = []

            for image_path in image_paths:
                image = cv2.imread(str(image_path))

                if image is None:
                    continue

                embedding = self.engine.get_embedding(image)

                if embedding is None:
                    continue

                embeddings.append(embedding)
                if max_photos_per_employee and len(embeddings) >= max_photos_per_employee:
                    break

            if embeddings:
                self.employee_embeddings[employee_id] = embeddings
                print(
                    f"Loaded {employee_id}: {len(embeddings)} photo(s)"
                )
            else:
                print(f"No usable face photos for {employee_id}")

        if use_cache and self.employee_embeddings:
            embedding_cache.save_cache(cache_path, signature, self.employee_embeddings)

        return self.employee_embeddings

    def recognize_employee(self, person_crop):
        return self.engine.recognize(
            person_crop,
            self.employee_embeddings
        )
