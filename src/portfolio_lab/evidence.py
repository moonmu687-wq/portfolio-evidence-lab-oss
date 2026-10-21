"""Immutable input hashes and provenance for offline replay."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


class DataError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj):
    payload = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False, default=str)
    write_bytes_atomic(path, payload.encode("utf8"))


def write_bytes_atomic(path: Path, payload: bytes):
    """Preserve exact hashes when restoring a failed update's previous files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def input_manifest(paths: list[Path], root: Path):
    return [
        {"path": p.relative_to(root).as_posix(), "sha256": sha256(p), "bytes": p.stat().st_size}
        for p in sorted(set(paths))
    ]


def verify_manifest(manifest, root: Path, archived=False):
    for item in manifest:
        path = (root / (item.get("object_path", item["path"]) if archived else item["path"])).resolve()
        if not path.is_relative_to(root.resolve()):
            raise DataError("Manifest path escapes project")
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise DataError(f"Evidence changed: {item['path']}")


def archive_inputs(manifest, root: Path):
    """Content-addressed snapshots preserve old runs when the current SSOT advances."""
    for item in manifest:
        obj = root / "private/objects" / item["sha256"][:2] / item["sha256"]
        obj.parent.mkdir(parents=True, exist_ok=True)
        if not obj.exists():
            with obj.open("xb") as handle:
                handle.write((root / item["path"]).read_bytes())
        if sha256(obj) != item["sha256"]:
            raise DataError("Archived object hash mismatch")
        item["object_path"] = obj.relative_to(root).as_posix()
    return manifest


def materialize(manifest, root, destination):
    if destination.exists():
        raise DataError("Replay destination must not already exist")
    entries = manifest["inputs"] + manifest["code"]
    verify_manifest(entries, root, archived=True)
    destination.mkdir(parents=True)
    for item in entries:
        target = (destination / item["path"]).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise DataError("Replay path escapes destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / item["object_path"]).read_bytes())
