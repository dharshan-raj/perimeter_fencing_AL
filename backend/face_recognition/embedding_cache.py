"""Disk cache for enrolled employee embeddings so startup does not re-embed every photo."""
import hashlib
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CACHE_NAME = ".embeddings_cache.npz"


def list_employee_photos(photos_dir, max_photos=None):
    """{employee_id: [photo paths]} in a stable, sorted order."""
    photos_dir = Path(photos_dir)
    result = {}
    if not photos_dir.exists():
        return result
    for folder in sorted(p for p in photos_dir.iterdir() if p.is_dir()):
        files = sorted(f for f in folder.iterdir()
                       if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES)
        result[folder.name] = files
    return result


def photos_signature(photos_dir, max_photos_per_employee):
    """Hash of every photo's name, size and mtime plus the photo cap."""
    digest = hashlib.sha256()
    digest.update(f"cap={max_photos_per_employee}".encode())
    for employee, files in list_employee_photos(photos_dir).items():
        digest.update(employee.encode())
        for f in files:
            stat = f.stat()
            digest.update(f"{f.name}:{stat.st_size}:{int(stat.st_mtime)}".encode())
    return digest.hexdigest()


def load_cache(cache_path, signature):
    """Return {employee_id: [embeddings]} if the cache matches signature, else None."""
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as data:
            if str(data["signature"]) != signature:
                return None
            embeddings = {}
            for key in data.files:
                if key.startswith("emp::"):
                    embeddings[key[5:]] = [row for row in data[key]]
            return embeddings
    except Exception as exc:
        log.warning("Ignoring unreadable embedding cache %s: %s", cache_path, exc)
        return None


def save_cache(cache_path, signature, embeddings):
    """Best effort. A failure to write the cache must never break startup."""
    try:
        arrays = {f"emp::{name}": np.stack(vectors).astype(np.float32)
                  for name, vectors in embeddings.items() if vectors}
        np.savez_compressed(Path(cache_path), signature=np.array(signature), **arrays)
    except Exception as exc:
        log.warning("Could not write embedding cache %s: %s", cache_path, exc)
