"""Locate the executing package and its framework assets."""

from __future__ import annotations

import os
from pathlib import Path

from cardine.shared.errors import CardineError


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def source_checkout() -> Path | None:
    """Return the checkout that contains the executing package, if any."""
    source = PACKAGE_ROOT.parent
    root = source.parent
    if source.name == "src" and (root / "VERSION").is_file():
        return root
    return None


_checkout = source_checkout()
SCRIPTS_ROOT = _checkout / "scripts" if _checkout is not None else None


def framework_root() -> Path:
    """Resolve the development override, bundled assets, or source checkout."""
    override = os.environ.get("CARDINE_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if root.is_dir():
            return root

    bundled = PACKAGE_ROOT / "_framework"
    if (bundled / "VERSION").is_file():
        return bundled

    checkout = source_checkout()
    if checkout is not None:
        return checkout
    raise CardineError("Cardine framework assets could not be located")
