"""Shared hashing helpers extracted from the legacy CLI."""

from __future__ import annotations

import hashlib


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
