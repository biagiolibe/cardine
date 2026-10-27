"""Compatibility entry point; the host module owns all read-guard policy."""

from cardine.hosts.read_guard import decision, extract_targets, main

__all__ = ["decision", "extract_targets", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
