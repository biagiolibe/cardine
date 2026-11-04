"""The Meridian read model reads queue, ADR log, and configuration without writing."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from cardine.legacy.conversion_reader import read_legacy_project
from cardine.shared.errors import CardineError
from conversion_fixture import queue_text, write_meridian_project


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode() + path.read_bytes())
    return digest.hexdigest()


class ConversionReaderTest(unittest.TestCase):
    def project(self, **options) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return write_meridian_project(Path(directory.name) / "project", **options)

    def test_lean_queue_states(self) -> None:
        root = self.project(queue=queue_text([
            ("[ ]", "10", "Open"), ("[/]", "11", "Started"), ("[x]", "12", "Done"),
            ("[-]", "13", "Cancelled"), ("[?]", "14", "Proposed")]))
        before = tree_digest(root)
        project = read_legacy_project(root)
        self.assertEqual(project.mode, "lean-delivery")
        self.assertEqual([row.task_id for row in project.open_rows], ["10"])
        self.assertEqual([row.task_id for row in project.in_progress_rows], ["11"])
        self.assertEqual(project.closed_ids, ("12",))
        self.assertEqual([row.state for row in project.rows],
                         ["open", "in_progress", "closed", "cancelled", "proposed"])
        self.assertEqual(project.diagnostics, ())
        self.assertEqual(tree_digest(root), before)

    def test_governed_queue_carries_review_and_status_words(self) -> None:
        root = self.project(governed=True, queue=queue_text(
            [("QUEUED", "20", "Open", "required"), ("READY_FOR_REVIEW", "21", "Review", "required"),
             ("DONE", "22", "Done", "none")], governed=True))
        project = read_legacy_project(root)
        self.assertEqual(project.mode, "governed-sdd")
        self.assertEqual([(row.task_id, row.state, row.review) for row in project.rows],
                         [("20", "open", "required"), ("21", "in_progress", "required"), ("22", "closed", "none")])

    def test_duplicate_ids_are_kept_and_reported(self) -> None:
        project = read_legacy_project(self.project(queue=queue_text([
            ("[ ]", "30", "First"), ("[x]", "30", "Again"), ("[ ]", "31", "Other")])))
        self.assertEqual(project.duplicate_ids, ("30",))
        self.assertEqual(len(project.rows), 3)
        self.assertIn("duplicate queue id 30", project.diagnostics)

    def test_unrecognized_status_is_a_diagnostic(self) -> None:
        project = read_legacy_project(self.project(queue=queue_text([("[~]", "40", "Odd")])))
        self.assertEqual(project.rows[0].state, "unknown")
        self.assertTrue(any("unrecognized status" in item for item in project.diagnostics))

    def test_no_queue(self) -> None:
        project = read_legacy_project(self.project())
        self.assertFalse(project.queue_present)
        self.assertEqual((project.rows, project.open_rows, project.closed_ids), ((), (), ()))
        self.assertTrue(any("no queue" in item for item in project.diagnostics))

    def test_adr_log_with_ids(self) -> None:
        log = ("# Decisions\n\n## ADR-0001: First\n\nStatus: Accepted\n\n## ADR-0002 Second\n\n"
               "## ADR-0001: Repeated\n")
        project = read_legacy_project(self.project(adr_log=log))
        self.assertTrue(project.adr_log_present)
        self.assertEqual([(entry.adr_id, entry.title, entry.status) for entry in project.adr_entries],
                         [("ADR-0001", "First", "Accepted"), ("ADR-0002", "Second", None)])
        self.assertEqual(project.adr_unnumbered, ())
        self.assertTrue(any("duplicate ADR-0001" in item for item in project.diagnostics))

    def test_adr_log_without_ids(self) -> None:
        project = read_legacy_project(self.project(adr_log="# ADR: Stops and Denials\n\n## Notes\n\ntext\n"))
        self.assertTrue(project.adr_log_present)
        self.assertEqual(project.adr_entries, ())
        self.assertEqual(project.adr_unnumbered, ("ADR: Stops and Denials",))

    def test_no_adr_log(self) -> None:
        project = read_legacy_project(self.project())
        self.assertFalse(project.adr_log_present)
        self.assertEqual((project.adr_entries, project.adr_unnumbered), ((), ()))

    def test_configuration(self) -> None:
        project = read_legacy_project(self.project(
            declaration={"version": 1, "preset": "lean"}, identity={"version": 1, "mode": "milestone"},
            candidate={"commands": ["make test"]}, flow_targets={"targets": []}))
        self.assertEqual(project.declaration, {"version": 1, "preset": "lean"})
        self.assertEqual(project.identity_mode, "milestone")
        self.assertEqual(project.candidate_validation, {"commands": ["make test"]})
        self.assertEqual(project.flow_targets, {"targets": []})

    def test_configuration_defaults(self) -> None:
        project = read_legacy_project(self.project())
        self.assertEqual((project.declaration, project.candidate_validation, project.flow_targets), (None, None, None))
        self.assertEqual(project.identity_mode, "opaque")

    def test_declared_locations_are_the_only_paths_read(self) -> None:
        root = self.project(
            declaration={"version": 1, "preset": "lean", "locations": {"queue": "work/Q.md", "adrLog": "log/adr.md"}},
            queue=queue_text([("[ ]", "50", "Default queue")]), adr_log="## ADR-0009 Default\n")
        (root / "work").mkdir()
        (root / "work" / "Q.md").write_text(queue_text([("[x]", "51", "Declared queue")]), encoding="utf-8")
        (root / "log").mkdir()
        (root / "log" / "adr.md").write_text("## ADR-0003 Declared\n", encoding="utf-8")
        project = read_legacy_project(root)
        self.assertEqual([row.task_id for row in project.rows], ["51"])
        self.assertEqual([entry.adr_id for entry in project.adr_entries], ["ADR-0003"])

    def test_undetectable_mode_is_a_diagnostic(self) -> None:
        project = read_legacy_project(self.project(workflow_lock="NOTHING"))
        self.assertIsNone(project.mode)
        self.assertTrue(any("workflow mode" in item for item in project.diagnostics))

    def test_not_a_meridian_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CardineError):
                read_legacy_project(Path(directory))

    def test_declared_path_outside_the_project_is_refused(self) -> None:
        root = self.project(declaration={"version": 1, "preset": "lean", "locations": {"queue": "link/Q.md"}})
        with tempfile.TemporaryDirectory() as outside:
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(CardineError):
                read_legacy_project(root)

    def test_malformed_declared_json_is_refused(self) -> None:
        root = self.project()
        (root / ".meridian" / "candidate-validation.json").write_text("[1]", encoding="utf-8")
        with self.assertRaises(CardineError):
            read_legacy_project(root)


if __name__ == "__main__":
    unittest.main()
