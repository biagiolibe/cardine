"""Compatibility adapter for tasks.state."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.tasks.state import (  # noqa: E402, F401
    STATE_MACHINES,
    SPIKE_MACHINE,
    SCHEMA_PATH,
    TaskStateInvalid,
    _invalid,
    _validate_schema,
    machine,
    validate_task_state,
    state_path,
    read_task_state,
)
