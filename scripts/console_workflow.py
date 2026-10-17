"""Compatibility adapter for shared.console_workflow."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.shared.console_workflow import (  # noqa: E402, F401
    PHASES,
    ID_PATTERN,
    LINK_PATTERN,
    HANDOFF_STATUS,
    RECORD_STATUS,
    RECORD_REVIEW,
    REVIEW_ATTEMPT,
    TASK_HEADING,
    QUEUE_HEADING,
    LEAN_QUEUE_WRAPPER,
    ConsoleError,
    Profile,
    PROFILES,
    QueueRow,
    _cell,
    parse_queue,
    link_target,
    has_link,
    IGNORED_RECORD_DIRECTORIES,
    is_task_record_path,
    record_matches,
    heading_title,
    record_status,
    record_review,
    handoff_status,
    latest_review_verdict,
    BranchFacts,
    Effective,
    effective_state,
)
