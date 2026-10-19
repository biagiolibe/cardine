"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES, names

from cardine.shared.errors import InternalStopError
from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir
from cardine.stops.registry import load_stop_registry
from cardine.tasks.identity import canonical_task_id
from cardine.worktree.storage import _verified_lifecycle_project
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from pathlib import Path
import argparse
import json
import os
import sys

JOURNAL_NAME = PRODUCT_NAMES.journal_name


JOURNAL_ROTATED_NAME = PRODUCT_NAMES.journal_rotated_name


JOURNAL_MAX_BYTES = 5 * 1024 * 1024


JOURNAL_VERSION = 1


JOURNALED_WORKTREE_COMMANDS = frozenset({"prepare", "check", "advance", "evidence", "cleanup"})


JOURNALED_INTEGRATE_COMMANDS = frozenset({"stage", "finalize", "abort"})


class LifecycleJournalEntry:
    """One journal line for a lifecycle command; holds only registered, non-sensitive fields."""

    def __init__(self) -> None:
        self.command: str | None = None
        self.task: str | None = None
        self.step: str | None = None
        self.stop_code: str | None = None
        self.blocked = False
        self.resume = False
        self.project: Path | None = None

    def begin(self, arguments: argparse.Namespace) -> None:
        if getattr(arguments, "command", None) != "worktree":
            return
        name = arguments.worktree_command
        if name == "integrate":
            if arguments.integrate_command not in JOURNALED_INTEGRATE_COMMANDS:
                return
            name = f"integrate {arguments.integrate_command}"
        elif name not in JOURNALED_WORKTREE_COMMANDS:
            return
        self.command = name
        try:
            self.task = canonical_task_id(arguments.task_id).removeprefix("task-")
        except CardineError:
            self.task = None
        self.resume = name == "prepare" and bool(getattr(arguments, "resume", False))
        self.project = getattr(arguments, "project", None)

    def observe(self, result: Mapping[str, object]) -> None:
        step = result.get("step") or result.get("next_action")
        if isinstance(step, str):
            self.step = step
        task = result.get("task_id")
        if isinstance(task, str):
            self.task = task

    def stopped(self, code: str | None) -> None:
        self.blocked = True
        if code is not None and code in load_stop_registry():
            self.stop_code = code

    def write(self, exit_code: int) -> None:
        if self.command is None:
            return
        if exit_code == 0:
            outcome = "ok"
        elif self.blocked:
            outcome = "blocked"
        else:
            outcome = "error"
        line: dict[str, object] = {
            "version": JOURNAL_VERSION,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": self.command,
            "task": self.task,
            "result": outcome,
            "exit": exit_code,
        }
        if self.step is not None:
            line["step"] = self.step
        if self.stop_code is not None and outcome == "blocked":
            line["stop_code"] = self.stop_code
            line["resolution"] = load_stop_registry()[self.stop_code]["resolution"]
        if self.resume:
            line["resume"] = True
        try:
            append_journal_line(_verified_lifecycle_project(self.project), line)
        except (OSError, CardineError, InternalStopError) as error:
            print(f"warning: lifecycle journal not written: {type(error).__name__}", file=sys.stderr)


def append_journal_line(project_root: Path, line: Mapping[str, object]) -> None:
    """Append one whole JSON line to the shared journal, rotating it past the size cap."""
    directory = canonical_git_common_dir(project_root)
    journal = directory / names().journal_name
    try:
        if journal.stat().st_size > JOURNAL_MAX_BYTES:
            os.replace(journal, directory / names().journal_rotated_name)
    except FileNotFoundError:
        pass
    data = (json.dumps(line, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if os.write(descriptor, data) != len(data):
            raise OSError("short journal write")
    finally:
        os.close(descriptor)
