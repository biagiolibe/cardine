"""Compatibility entry point; the host module owns all stop-audit policy."""

from cardine.hosts.stop_audit import audit, final_message, stop_audit_main as main

__all__ = ["audit", "final_message", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
