"""Receipt-covered host writes in the user's home or project settings.

The receipt lives outside the files it covers and records only digests, never
configuration text. Applying never runs unless the caller already holds the
explicit consent its `--apply` flag represents.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.file_operation import Operation, operation


@contextmanager
def host_operation(kind: str, anchor: Path, operation_in: Operation | None = None):
    """Yield the caller's operation, or serialize and open one anchored at `anchor`."""
    if operation_in is not None:
        yield operation_in
        return
    anchor = Path(anchor).resolve()
    with operation(receipts.host_path(kind, anchor), dict(kind=kind, anchor=str(anchor))) as active:
        yield active


def changed(active: Operation, wrote: bool) -> bool:
    """A resumed operation finishes work an earlier, killed invocation began."""
    return wrote or active.resumed
