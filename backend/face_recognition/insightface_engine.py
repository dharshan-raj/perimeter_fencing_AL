
import cv2
import numpy as np
from pathlib import Path
from insightface.app import FaceAnalysis


class InsightFaceEngine:
    def __init__(
        self,
        model_name="buffalo_l",
        match_threshold=0.45,
        root=None
    ):
        self.match_threshold = match_threshold

        if root is None:
            local_models = Path(__file__).resolve().parent.parent.parent / "models" / ".insightface"
            if local_models.exists():
                root = str(local_models)

        kwargs = {
            "name": model_name,
            "providers": ["CPUExecutionProvider"]
        }
        if root:
            kwargs["root"] = str(root)

        # CPU mode. We can configure GPU later.
        self.app = FaceAnalysis(**kwargs)

        self.app.prepare(
            ctx_id=-1,
            det_size=(640, 640)
        )

    def get_embedding(self, image):
        """
        Extract one face embedding from an image.

        Returns None if no face or multiple faces are detected.
        """
        if image is None or image.size == 0:
            return None

        faces = self.app.get(image)

        # For employee registration and person crops,
        # accept only one clearly detected face.
        if len(faces) != 1:
            return None

        embedding = faces[0].embedding.astype(np.float32)

        # Normalize embedding for cosine similarity.
        norm = np.linalg.norm(embedding)

        if norm == 0:
            return None

        return embedding / norm

    def compare(self, embedding1, embedding2):
        """Cosine similarity between two normalized embeddings."""
        return float(np.dot(embedding1, embedding2))

    def recognize(self, image, employee_embeddings):
        """
        employee_embeddings format:
        {
            "EMP001": [embedding1, embedding2],
            "EMP002": [embedding1]
        }
        """
        query_embedding = self.get_embedding(image)

        if query_embedding is None:
            return {
                "employee_id": None,
                "status": "NO_CLEAR_FACE",
                "similarity": None
            }

        best_employee = None
        best_score = -1.0

        for employee_id, embeddings in employee_embeddings.items():
            for registered_embedding in embeddings:
                score = self.compare(
                    query_embedding,
                    registered_embedding
                )

                if score > best_score:
                    best_score = score
                    best_employee = employee_id

        if best_employee is not None and best_score >= self.match_threshold:
            return {
                "employee_id": best_employee,
                "status": "MATCHED",
                "similarity": best_score
            }

        return {
            "employee_id": None,
            "status": "UNKNOWN",
            "similarity": best_score if best_score >= 0 else None
        }

    # ------------------------------------------------------------------
    # Added for multi-frame CCTV recognition. The methods above are unchanged.
    # ------------------------------------------------------------------

    def embed_best_face(self, image, min_det_score=0.5):
        """
        Find faces in a CCTV crop and embed the LARGEST one above the
        detection-confidence limit (unlike get_embedding, which rejects the
        image unless exactly one face is found).

        Returns {"embedding", "bbox", "det_score"} or None.
        """
        if image is None or image.size == 0:
            return None

        faces = [f for f in self.app.get(image)
                 if float(f.det_score) >= min_det_score]
        if not faces:
            return None

        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = face.embedding.astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return None

        return {
            "embedding": embedding / norm,
            "bbox": [float(v) for v in face.bbox],
            "det_score": float(face.det_score),
        }

    def match_embedding(self, embedding, employee_embeddings,
                        threshold=None, margin=0.0, top_k=2):
        """
        Score an embedding against every employee.

        An employee's score is the mean of their top_k photo similarities
        (more stable than one lucky photo). To be MATCHED the best employee
        must reach the threshold AND beat the runner-up by `margin`.

        status: MATCHED, UNKNOWN (below threshold) or AMBIGUOUS (too close
        to a second employee).
        """
        threshold = self.match_threshold if threshold is None else threshold
        scores = []
        for employee_id, vectors in employee_embeddings.items():
            if not vectors:
                continue
            sims = sorted((self.compare(embedding, v) for v in vectors), reverse=True)
            k = min(top_k, len(sims))
            scores.append((float(np.mean(sims[:k])), employee_id))

        if not scores:
            return {"employee_id": None, "status": "UNKNOWN",
                    "similarity": None, "margin": None}

        scores.sort(reverse=True)
        best_score, best_id = scores[0]
        gap = best_score - scores[1][0] if len(scores) > 1 else None

        if best_score < threshold:
            return {"employee_id": None, "status": "UNKNOWN",
                    "similarity": best_score, "margin": gap}
        if gap is not None and gap < margin:
            return {"employee_id": None, "status": "AMBIGUOUS",
                    "similarity": best_score, "margin": gap}
        return {"employee_id": best_id, "status": "MATCHED",
                "similarity": best_score, "margin": gap}
