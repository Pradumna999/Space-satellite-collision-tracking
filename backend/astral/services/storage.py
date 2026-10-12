"""Object store on the local filesystem (production can mount a volume or
swap in an S3-compatible implementation with the same interface).

Keys are generated server-side (``<prefix>/<uuid4 hex>``) and validated on
every access; user-supplied file names never become paths.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from ..settings import get_settings

_KEY = re.compile(r"^(uploads|snapshots|reports|models|ml-data)/[0-9a-f]{32}(\.[a-z0-9]{1,8})?$")


class StorageError(ValueError):
    pass


def _root() -> Path:
    root = get_settings().storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    if not _KEY.match(key):
        raise StorageError("invalid storage key")
    p = (_root() / key).resolve()
    if _root() not in p.parents:
        raise StorageError("storage key escapes root")
    return p


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(prefix: str, data: bytes, ext: str = "") -> tuple[str, str]:
    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return key, sha256(data)


def get(key: str) -> bytes:
    p = _path(key)
    if not p.exists():
        raise StorageError("object not found")
    return p.read_bytes()


def verify(key: str, expected_sha256: str) -> bool:
    return sha256(get(key)) == expected_sha256


def delete(key: str) -> None:
    p = _path(key)
    if p.exists():
        p.unlink()
