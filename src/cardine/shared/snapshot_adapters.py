"""Scoped adapters for explicit read-only installation snapshots.

Product readers leave these unset. The installation reader supplies its own
vocabulary mapping without changing the product schema or creating import cycles.
"""
from contextvars import ContextVar

state_adapter = ContextVar("snapshot_state_adapter", default=None)
status_adapter = ContextVar("snapshot_status_adapter", default=None)
# Reads (block, following zone) of the execution-assets capability from a workflow text.
execution_assets_adapter = ContextVar("snapshot_execution_assets_adapter", default=None)
