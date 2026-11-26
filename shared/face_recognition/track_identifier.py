# ============================================================
# FILE: shared/face_recognition/track_identifier.py
# PURPOSE: Multi-frame asynchronous face identity resolver per ByteTrack tracking ID
# USE CASE: Shared Infrastructure (Face Recognition)
# DEBUG TIPS:
#   - Runs InsightFace on a background thread so YOLO + Headcount run at full FPS
#   - Tune face_votes_required and face_min_person_height in shared/config.py
# ============================================================

"""
Multi-frame identity resolution for tracked people.

Instead of deciding from one frame, each tracked person (ByteTrack ID) collects
several good-quality face observations. Identity is locked only after enough
consistent matches, and "Unknown" is declared only after enough good attempts.

States:
    PENDING       still collecting evidence (person far away, blurry, too few frames)
    IDENTIFIED    consistent matches reached; name is locked
    UNIDENTIFIED  enough good-quality attempts and no employee matched
"""
import logging
import threading
import time
from collections import defaultdict

from .face_quality import prepare_person_crop, face_blur_score, is_person_big_enough

log = logging.getLogger(__name__)

PENDING = "PENDING"
IDENTIFIED = "IDENTIFIED"
UNIDENTIFIED = "UNIDENTIFIED"


class TrackIdentifier:
    def __init__(self, registry, *, threshold=0.40, margin=0.05, votes_required=2,
                 min_person_height=150, min_face_px=32, min_det_score=0.5,
                 min_blur=15.0, unknown_attempts=5, retry_interval=0.6,
                 unknown_retry_interval=2.0, max_per_cycle=1, lost_after=3.0):
        self.registry = registry
        self.threshold = threshold
        self.margin = margin
        self.votes_required = max(1, int(votes_required))
        self.min_person_height = min_person_height
        self.min_face_px = min_face_px
        self.min_det_score = min_det_score
        self.min_blur = min_blur
        self.unknown_attempts = max(1, int(unknown_attempts))
        self.retry_interval = retry_interval
        self.unknown_retry_interval = unknown_retry_interval
        self.max_per_cycle = max(1, int(max_per_cycle))
        self.lost_after = lost_after
        self._tracks = {}
        self._lock = threading.Lock()
        self._worker_busy = False

    @classmethod
    def from_settings(cls, registry, settings):
        return cls(
            registry,
            threshold=settings.face_match_threshold,
            margin=settings.face_match_margin,
            votes_required=settings.face_votes_required,
            min_person_height=settings.face_min_person_height,
            min_face_px=settings.face_min_face_px,
            min_det_score=settings.face_min_det_score,
            min_blur=settings.face_min_blur,
            unknown_attempts=settings.face_unknown_attempts,
            retry_interval=settings.face_retry_interval,
            max_per_cycle=settings.face_max_per_cycle,
        )

    # ------------------------------------------------------------------

    def _new_track(self, now):
        return {
            "state": PENDING, "name": None, "score": None,
            "attempts": 0, "no_face": 0, "too_small": 0, "blurry": 0, "rejected": 0,
            "votes": defaultdict(int), "scores": defaultdict(list),
            "next_try": 0.0, "last_seen": now,
        }

    def get(self, track_id):
        """Current identity for a track as a small dict."""
        st = self._tracks.get(track_id)
        if st is None:
            return {"state": PENDING, "name": None, "score": None, "attempts": 0}
        return {"state": st["state"], "name": st["name"],
                "score": st["score"], "attempts": st["attempts"]}

    def update(self, people, frame, now=None):
        """
        Advance identification for the people in this frame and write
        `name`, `identity_state` and `identity_score` onto each person dict.
        Only `max_per_cycle` faces are processed per call to keep latency low.
        """
        now = time.time() if now is None else now
        candidates = []
        for person in people:
            tid = person["id"]
            st = self._tracks.setdefault(tid, self._new_track(now))
            st["last_seen"] = now
            if st["state"] == IDENTIFIED:
                continue
            if not is_person_big_enough(person["box"], self.min_person_height):
                continue
            if now < st["next_try"]:
                continue
            candidates.append((person["box"][3] - person["box"][1], tid, person))

        # Prioritize closest (tallest) first.
        candidates.sort(key=lambda c: -c[0])
        for _, tid, person in candidates[: self.max_per_cycle]:
            try:
                self._observe(self._tracks[tid], person, frame, now)
            except Exception:
                log.exception("Face observation failed for track %s", tid)

        self._prune(now)
        self._apply_labels(people)
        return people

    def _apply_labels(self, people):
        for person in people:
            info = self.get(person["id"])
            person["identity_state"] = info["state"]
            person["identity_score"] = info["score"]
            if info["state"] == IDENTIFIED:
                person["name"] = info["name"].capitalize()
            elif info["state"] == UNIDENTIFIED:
                person["name"] = "Unknown"
            else:
                person["name"] = None

    def update_async(self, people, frame, now=None):
        """
        Non-blocking update for the live camera loop: immediately applies known
        names to `people` and runs InsightFace in a background daemon thread so
        YOLO + ByteTrack + Gate 3 Headcount always run at full FPS.
        """
        now = time.time() if now is None else now
        candidates = []
        with self._lock:
            for person in people:
                tid = person["id"]
                st = self._tracks.setdefault(tid, self._new_track(now))
                st["last_seen"] = now
                if st["state"] == IDENTIFIED:
                    continue
                if not is_person_big_enough(person["box"], self.min_person_height):
                    continue
                if now < st["next_try"]:
                    continue
                candidates.append((person["box"][3] - person["box"][1], tid, dict(person)))
            self._prune(now)
            self._apply_labels(people)

            if not candidates or self._worker_busy:
                return people
            candidates.sort(key=lambda c: -c[0])
            selected = candidates[: self.max_per_cycle]
            self._worker_busy = True

        frame_copy = frame.copy()

        def _run():
            try:
                for _, tid, person_copy in selected:
                    with self._lock:
                        st = self._tracks.get(tid)
                    if st is not None:
                        self._observe(st, person_copy, frame_copy, time.time())
            except Exception:
                log.exception("Background face observation failed")
            finally:
                with self._lock:
                    self._worker_busy = False

        threading.Thread(target=_run, daemon=True, name="face-v2-worker").start()
        return people

    # ------------------------------------------------------------------

    def _observe(self, st, person, frame, now):
        st["next_try"] = now + (self.unknown_retry_interval
                                if st["state"] == UNIDENTIFIED else self.retry_interval)

        crop, scale = prepare_person_crop(frame, person["box"])
        if crop is None:
            st["no_face"] += 1
            return

        engine = self.registry.engine
        found = engine.embed_best_face(crop, min_det_score=self.min_det_score)
        if found is None:
            st["no_face"] += 1
            # Back off on seated/back-turned people when retry_interval > 0
            if self.retry_interval > 0 and st["no_face"] >= 2:
                st["next_try"] = now + min(4.0, self.retry_interval * (1 + st["no_face"]))
            return

        x1, y1, x2, y2 = found["bbox"]
        if (x2 - x1) / scale < self.min_face_px:
            st["too_small"] += 1
            return
        if face_blur_score(crop, found["bbox"]) < self.min_blur:
            st["blurry"] += 1
            return

        st["attempts"] += 1
        result = engine.match_embedding(
            found["embedding"], self.registry.employee_embeddings,
            threshold=self.threshold, margin=self.margin,
        )

        if result["status"] == "MATCHED":
            name = result["employee_id"]
            st["votes"][name] += 1
            st["scores"][name].append(result["similarity"])
            self._maybe_lock(st, name)
        else:
            st["rejected"] += 1

        if st["state"] != IDENTIFIED and st["attempts"] >= self.unknown_attempts:
            st["state"] = UNIDENTIFIED

    def _maybe_lock(self, st, name):
        votes = st["votes"][name]
        others = max((v for k, v in st["votes"].items() if k != name), default=0)
        # Lock only when this name has enough votes and clearly out-votes the rest.
        if votes >= self.votes_required and votes > 2 * others:
            scores = st["scores"][name]
            st["state"] = IDENTIFIED
            st["name"] = name
            st["score"] = sum(scores) / len(scores)

    def _prune(self, now):
        lost = [tid for tid, st in self._tracks.items()
                if now - st["last_seen"] > self.lost_after]
        for tid in lost:
            del self._tracks[tid]
