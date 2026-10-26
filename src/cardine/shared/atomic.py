"""Whole-file writes that a killed process cannot leave half written."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cardine.shared.errors import CardineError


def file_digest(path: Path) -> str | None:
    """SHA-256 of a regular file's bytes; None when absent. Links and directories are refused."""
    if path.is_symlink():
        raise CardineError(f"refusing to write through a symlink: {path}")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except IsADirectoryError as error:
        raise CardineError(f"expected a regular file: {path}") from error


def _temporary(path: Path, data: bytes) -> Path:
    # One fixed name per target: a killed attempt leaves a single residue that
    # the next attempt overwrites, never an accumulating set of temporaries.
    temporary = path.with_name(f".{path.name}.cardine-tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return temporary


def replace_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    """Replace or create `path` atomically, keeping an existing file's permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary = _temporary(path, data)
    try:
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def create_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Create `path` complete or not at all; an existing file is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary(path, data)
    try:
        os.chmod(temporary, mode)
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
