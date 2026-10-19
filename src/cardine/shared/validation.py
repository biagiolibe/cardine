"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path

from cardine.shared.errors import CardineError


def _required_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CardineError(f"{label} must be a JSON object")
    return value

def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CardineError(f"{label} must be a non-empty string")
    return value

def _required_positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise CardineError(f"{label} must be a positive integer")
    return value

def _required_string_list(value: object, label: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "a non-empty" if non_empty else "a"
        raise CardineError(f"{label} must be {qualifier} list of strings")
    result = tuple(_required_string(item, f"{label} item") for item in value)
    if len(set(result)) != len(result):
        raise CardineError(f"{label} must not contain duplicates")
    return result

def _repository_relative_path(value: object, label: str) -> str:
    text = _required_string(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or text != path.as_posix() or text in {".", ""}:
        raise CardineError(f"{label} must be a normalized repository-relative path")
    return text
