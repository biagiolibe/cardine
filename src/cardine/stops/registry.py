"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path
import json

from cardine.shared.errors import InternalStopError
from cardine.shared.paths import SCRIPTS_ROOT


STOP_REGISTRY_PATH = Path("capabilities/stop-codes-v1.json")

STOP_REGISTRY_VERSION = 1

STOP_REGISTRY_FIELDS = frozenset(
    {"code", "class", "kind", "workflows", "step", "emitter", "human_decision", "resume", "summary",
     "tool_hint", "test", "resolution"}
)

_stop_registry_cache: dict[str, dict[str, object]] | None = None

def load_stop_registry() -> dict[str, dict[str, object]]:
    """Load the stop-code registry that every CLI stop is emitted through."""
    global _stop_registry_cache
    if _stop_registry_cache is None:
        path = SCRIPTS_ROOT.parent / STOP_REGISTRY_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InternalStopError(f"stop-code registry is unreadable: {path}") from error
        stops = data.get("stops") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("version") != STOP_REGISTRY_VERSION or not isinstance(stops, list):
            raise InternalStopError(f"stop-code registry must be version {STOP_REGISTRY_VERSION} with a stops array: {path}")
        registry: dict[str, dict[str, object]] = {}
        for entry in stops:
            code = entry.get("code") if isinstance(entry, dict) else None
            if (
                not isinstance(code, str)
                or code in registry
                or entry.get("resolution") not in {"guardrail", "recoverable", "failing-work"}
                or not isinstance(entry.get("human_decision"), bool)
                or ((entry.get("resolution") == "guardrail") != entry.get("human_decision"))
                or not isinstance(entry.get("resume"), str)
                or not isinstance(entry.get("summary"), str)
                or not set(entry) <= STOP_REGISTRY_FIELDS
            ):
                raise InternalStopError(f"stop-code registry has an invalid or duplicate entry: {code!r}")
            registry[code] = entry
        _stop_registry_cache = registry
    return _stop_registry_cache
