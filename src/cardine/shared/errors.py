"""Shared errors helpers extracted from the legacy CLI."""

from __future__ import annotations

from collections.abc import Callable


class CardineError(RuntimeError):
    """Raised when an upgrade cannot be safely planned or applied."""


class InternalStopError(Exception):
    """Raised when the CLI asks for a stop that the registry cannot format."""


class CardineStop(CardineError):
    """A registered diagnostic carrying typed cause and recovery metadata."""

    def __init__(self, code: str, line: str, *, render: Callable[[], str] | None = None) -> None:
        super().__init__(line)
        self.code = code
        self._render = render
        self.detail: str | None = None
        self.resume: Callable[[], str] | None = None

    def __str__(self) -> str:
        return self._render() if self._render is not None else super().__str__()
