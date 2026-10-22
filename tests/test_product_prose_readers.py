"""No product consumer reads queue rows or record, handoff, and review status lines."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cardine.legacy.console_workflow import (
    PROFILES, handoff_status, latest_review_verdict, parse_queue, record_review, record_status,
)
from cardine.shared.console_workflow import ConsoleError

# The static search of work item 7: names of the prose parsers and the two literal reads of a record
# `Status` line or a queue row, anywhere outside `cardine.legacy`. The frozen hooks are not searched.
NAMES = (r"parse_queue|record_status|record_review|handoff_status|latest_review_verdict|effective_state|"
         r"QUEUE_HEADING|RECORD_STATUS|RECORD_REVIEW|HANDOFF_STATUS|REVIEW_ATTEMPT|TASK_HEADING|"
         r"LEAN_QUEUE_WRAPPER|link_target|has_link|_queue_task_rows")
SEARCH = rf"\b(?:{NAMES})\b|read_task_field\([^)]*\"Status\""
SCOPE = ("src", "scripts")

# Every remaining hit and its reason. A ratchet: the set can only shrink. Moving these under
# `cardine.legacy` is blocked by the import-graph test of the installation snapshot, which forbids
# a product import of `cardine.legacy`, and by the plan, which keeps the explicit import isolated
# until work item 10.
ALLOWED = {
    "src/cardine/tasks/importer.py": (
        "the explicit `cardine task state import` reads a legacy record's Status and the queue rows once to "
        "register state; it is never called as missing-state recovery (tests/test_task_status_gates.py)"),
    "src/cardine/integration/projections.py": "defines `_queue_task_rows`, whose only caller is the importer",
    "scripts/cardine_cli.py": "re-exports `_queue_task_rows` for the importer's tests; reads nothing itself",
}


class ProductProseReaderTest(unittest.TestCase):
    def test_static_search_finds_only_the_documented_remaining_readers(self) -> None:
        tracked = subprocess.run(["git", "ls-files", "--", *SCOPE], cwd=ROOT, capture_output=True,
                                 text=True, check=True).stdout.split()
        pattern = re.compile(SEARCH)
        hits = sorted(name for name in tracked
                      if name.endswith(".py") and not name.startswith("src/cardine/legacy/")
                      and pattern.search((ROOT / name).read_text(encoding="utf-8")))
        self.assertEqual(hits, sorted(ALLOWED))

    def test_product_console_and_briefing_import_no_queue_or_prose_parser(self) -> None:
        for relative in ("src/cardine/console/snapshot.py", "src/cardine/console/state.py",
                         "src/cardine/hosts/briefing.py", "scripts/console_workflow.py"):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("cardine.legacy"), relative)
                    names = {alias.name for alias in node.names}
                    self.assertFalse(names & set(NAMES.split("|")), (relative, names))

    def test_console_and_briefing_never_name_a_queue_file(self) -> None:
        for path in [*(ROOT / "src/cardine/console").glob("*.py"), ROOT / "src/cardine/hosts/briefing.py"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"QUEUE(_ARCHIVE)?\.md|\.queue\b", str(path))


class LegacyParserTest(unittest.TestCase):
    """The installation snapshot keeps its prose parsers, now under `cardine.legacy`."""

    def test_record_review_values_are_strict(self) -> None:
        for value, expected in (
            ("REQUIRED", "REQUIRED"), (" NOT REQUIRED ", "NOT REQUIRED"),
            ("", None), ("required", None), ("OPTIONAL", None),
        ):
            with self.subTest(value=value):
                self.assertEqual(record_review(f"Review: {value}\n"), expected)
        self.assertIsNone(record_review("Status: in_review\n"))

    def test_status_handoff_and_verdict_parsers(self) -> None:
        self.assertEqual(record_status("Status: `in_review`\n"), "in_review")
        self.assertEqual(handoff_status("- Status: `done`\n"), "done")
        self.assertEqual(latest_review_verdict("## Attempt 1 — CHANGES_REQUESTED\n## Attempt 2 — APPROVE\n"), "APPROVE")
        self.assertIsNone(latest_review_verdict("# Review\n"))

    def test_queue_parser_reads_sections_and_rejects_unknown_status(self) -> None:
        header = "| Status | ID | Title | Priority | Depends on | File |\n|---|---|---|---|---|---|\n"
        queue = "# Queue\n\n## Program Queue\n\n### Phase 1\n\n" + header + "| `[ ]` | 001 | First | P2 | — | [001](001.md) |\n"
        row = parse_queue(queue, "fixture", PROFILES["single"])[0]
        self.assertEqual((row.task_id, row.status, row.section, row.checkbox),
                         ("001", "queued", ("Program Queue", "Phase 1"), True))
        with self.assertRaisesRegex(ConsoleError, "Unknown task status"):
            parse_queue(queue.replace("`[ ]`", "`[?]`"), "fixture", PROFILES["single"])


if __name__ == "__main__":
    unittest.main()
