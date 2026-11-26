import numpy as np
import pytest

from shared.face_recognition import embedding_cache
from shared.face_recognition.face_quality import (
    face_blur_score, is_person_big_enough, prepare_person_crop,
)
from shared.face_recognition.insightface_engine import InsightFaceEngine
from shared.face_recognition.track_identifier import (
    IDENTIFIED, PENDING, UNIDENTIFIED, TrackIdentifier,
)


# ----------------------------------------------------------------- fakes

class FakeEngine:
    """Replays scripted face observations; no InsightFace needed."""
    def __init__(self, script):
        self.script = list(script)   # each item: None | (name_or_None, face_width)
        self.calls = 0

    def embed_best_face(self, image, min_det_score=0.5):
        self.calls += 1
        item = self.script.pop(0) if self.script else None
        if item is None:
            return None
        name, width = item
        return {"embedding": name, "bbox": [0, 0, width, width], "det_score": 0.9}

    def match_embedding(self, embedding, employees, threshold=None, margin=0.0, top_k=2):
        if embedding is None:
            return {"employee_id": None, "status": "UNKNOWN", "similarity": 0.1}
        return {"employee_id": embedding, "status": "MATCHED", "similarity": 0.6}


class FakeRegistry:
    def __init__(self, script):
        self.engine = FakeEngine(script)
        self.employee_embeddings = {"dharshan": [1], "dinesh": [1]}


def noisy_frame():
    rng = np.random.default_rng(1)
    return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)


def person(tid=1, h=300):
    return {"id": tid, "box": [400, 100, 520, 100 + h], "confidence": 0.9}


def make(script, **kw):
    kw.setdefault("min_blur", 0.0)
    kw.setdefault("retry_interval", 0.0)
    return TrackIdentifier(FakeRegistry(script), **kw), noisy_frame()


# ----------------------------------------------------- track identifier

def test_identity_locks_only_after_enough_consistent_votes():
    ident, frame = make([("dharshan", 60)] * 3, votes_required=2)
    p = person()
    ident.update([p], frame, now=1.0)
    assert p["identity_state"] == PENDING and p["name"] is None
    ident.update([p], frame, now=2.0)
    assert p["identity_state"] == IDENTIFIED and p["name"] == "Dharshan"


def test_identified_name_is_locked_and_stops_using_the_cpu():
    ident, frame = make([("dharshan", 60)] * 2)
    p = person()
    ident.update([p], frame, now=1.0)
    ident.update([p], frame, now=2.0)
    calls = ident.registry.engine.calls
    ident.update([p], frame, now=3.0)
    assert ident.registry.engine.calls == calls
    assert p["name"] == "Dharshan"


def test_conflicting_matches_do_not_lock():
    ident, frame = make([("dharshan", 60), ("dinesh", 60), ("dharshan", 60), ("dinesh", 60)])
    p = person()
    for t in range(4):
        ident.update([p], frame, now=float(t))
    assert p["identity_state"] != IDENTIFIED


def test_unknown_only_after_enough_good_attempts():
    ident, frame = make([(None, 60)] * 5, unknown_attempts=5)
    p = person()
    for t in range(4):
        ident.update([p], frame, now=float(t))
    assert p["identity_state"] == PENDING and p["name"] is None
    ident.update([p], frame, now=10.0)
    assert p["identity_state"] == UNIDENTIFIED and p["name"] == "Unknown"


def test_unidentified_person_can_still_become_identified_later():
    ident, frame = make([(None, 60)] * 2 + [("dinesh", 60)] * 2,
                        unknown_attempts=2, unknown_retry_interval=0.0)
    p = person()
    for t in range(4):
        ident.update([p], frame, now=float(t))
    assert p["identity_state"] == IDENTIFIED and p["name"] == "Dinesh"


def test_far_away_person_is_never_attempted():
    ident, frame = make([("dharshan", 60)] * 5, min_person_height=150)
    p = person(h=80)
    for t in range(5):
        ident.update([p], frame, now=float(t))
    assert ident.registry.engine.calls == 0
    assert p["identity_state"] == PENDING


def test_small_faces_are_rejected_and_not_counted_as_unknown():
    ident, frame = make([("dharshan", 10)] * 6, min_face_px=32, unknown_attempts=2)
    p = person()
    for t in range(6):
        ident.update([p], frame, now=float(t))
    assert p["identity_state"] == PENDING
    assert ident.get(1)["attempts"] == 0


def test_blurry_faces_are_rejected():
    ident, _ = make([("dharshan", 60)] * 3, min_blur=1e9)
    flat = np.full((720, 1280, 3), 128, dtype=np.uint8)
    p = person()
    for t in range(3):
        ident.update([p], flat, now=float(t))
    assert ident.get(1)["attempts"] == 0 and p["identity_state"] == PENDING


def test_only_max_per_cycle_people_are_processed_closest_first():
    ident, frame = make([("dharshan", 60)] * 5, max_per_cycle=1)
    near, far = person(1, h=400), person(2, h=200)
    ident.update([far, near], frame, now=1.0)
    assert ident.get(1)["attempts"] == 1
    assert ident.get(2)["attempts"] == 0


def test_lost_tracks_are_pruned():
    ident, frame = make([("dharshan", 60)] * 2, lost_after=3.0)
    ident.update([person()], frame, now=1.0)
    ident.update([], frame, now=10.0)
    assert ident.get(1)["state"] == PENDING and 1 not in ident._tracks


# ----------------------------------------------------------- face quality

def test_prepare_crop_upscales_small_crops():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    crop, scale = prepare_person_crop(frame, [100, 100, 160, 300], min_width=240)
    assert scale > 1 and crop.shape[1] >= 239


def test_prepare_crop_handles_bad_input():
    assert prepare_person_crop(None, [0, 0, 1, 1])[0] is None
    assert prepare_person_crop(np.zeros((10, 10, 3), np.uint8), [5, 5, 5, 9])[0] is None


def test_blur_score_separates_sharp_from_flat():
    sharp = noisy_frame()[:200, :200]
    flat = np.full((200, 200, 3), 120, dtype=np.uint8)
    assert face_blur_score(sharp, [0, 0, 200, 200]) > face_blur_score(flat, [0, 0, 200, 200])


def test_person_height_gate():
    assert is_person_big_enough([0, 0, 50, 200], 150)
    assert not is_person_big_enough([0, 0, 50, 100], 150)


# ---------------------------------------------------------------- matching

def make_engine_for_matching():
    engine = InsightFaceEngine.__new__(InsightFaceEngine)   # skip loading the model
    engine.match_threshold = 0.45
    return engine


def unit(*v):
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


def test_match_embedding_matches_clear_winner():
    e = make_engine_for_matching()
    emps = {"a": [unit(1, 0, 0)], "b": [unit(0, 1, 0)]}
    r = e.match_embedding(unit(1, 0.1, 0), emps, threshold=0.4, margin=0.05)
    assert r["status"] == "MATCHED" and r["employee_id"] == "a"


def test_match_embedding_below_threshold_is_unknown():
    e = make_engine_for_matching()
    r = e.match_embedding(unit(0, 0, 1), {"a": [unit(1, 0, 0)]}, threshold=0.4)
    assert r["status"] == "UNKNOWN" and r["employee_id"] is None


def test_match_embedding_close_second_is_ambiguous():
    e = make_engine_for_matching()
    emps = {"a": [unit(1, 0.05, 0)], "b": [unit(1, -0.05, 0)]}
    r = e.match_embedding(unit(1, 0, 0), emps, threshold=0.4, margin=0.05)
    assert r["status"] == "AMBIGUOUS" and r["employee_id"] is None


# ------------------------------------------------------------------- cache

def test_embedding_cache_roundtrip_and_invalidation(tmp_path):
    folder = tmp_path / "photos" / "alice"
    folder.mkdir(parents=True)
    (folder / "1.jpg").write_bytes(b"x")
    sig = embedding_cache.photos_signature(tmp_path / "photos", 5)
    cache = tmp_path / "cache.npz"
    embedding_cache.save_cache(cache, sig, {"alice": [unit(1, 0, 0), unit(0, 1, 0)]})

    loaded = embedding_cache.load_cache(cache, sig)
    assert list(loaded) == ["alice"] and len(loaded["alice"]) == 2

    (folder / "2.jpg").write_bytes(b"yy")       # a photo was added
    new_sig = embedding_cache.photos_signature(tmp_path / "photos", 5)
    assert new_sig != sig
    assert embedding_cache.load_cache(cache, new_sig) is None
    assert embedding_cache.photos_signature(tmp_path / "photos", 10) != new_sig
