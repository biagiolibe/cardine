"""Dispatch the development command to this checkout's existing CLI."""

from pathlib import Path
import runpy
import sys


def legacy_main() -> None:
    """Select this checkout explicitly, ahead of any inherited MERIDIAN_ROOT."""
    root = Path(__file__).resolve().parents[2]
    original_argv = sys.argv
    sys.argv = [original_argv[0], "--framework-root", str(root), *original_argv[1:]]
    try:
        runpy.run_path(str(root / "scripts" / "meridian.py"), run_name="__main__")
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    legacy_main()
