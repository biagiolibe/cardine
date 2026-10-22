"""Errors and identifiers shared by the read-only project console."""

from __future__ import annotations

import re


ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class ConsoleError(Exception):
    """Project state could not be read without ambiguity."""
