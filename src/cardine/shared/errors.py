"""Shared errors helpers extracted from the legacy CLI."""

from __future__ import annotations

from collections.abc import Callable


class MeridianError(RuntimeError):
    """Raised when an upgrade cannot be safely planned or applied."""


class InternalStopError(Exception):
    """Raised when the CLI asks for a stop that the registry cannot format."""


class MeridianStop(MeridianError):
    """A registered stop; its message is the complete `BLOCKED <CODE>: ...` line."""

    def __init__(self, code: str, line: str, *, render: Callable[[], str] | None = None) -> None:
        super().__init__(line)
        self.code = code
        self._render = render

    def __str__(self) -> str:
        return self._render() if self._render is not None else super().__str__()
