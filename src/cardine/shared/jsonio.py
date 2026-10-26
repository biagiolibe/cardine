"""Shared jsonio bindings extracted from the legacy CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from cardine.shared.errors import CardineError


def json_bytes(value: dict[str, object]) -> bytes:
    """The exact bytes `_write_json_atomic` stores for `value`."""
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _write_json_atomic(path: Path, value: dict[str, object], *, exclusive: bool = False) -> None:
    from cardine.shared.git import invalidate_facts
    invalidate_facts()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json_bytes(value)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CardineError(f"cannot read {label} at {path}: {error}") from error
    if not isinstance(value, dict):
        raise CardineError(f"{label} must be a JSON object: {path}")
    return value
