"""The `run` help states what `run` performs, not a read-only preview (C3d)."""
import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest

from cardine.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def help_of(*argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer), self_exit():
        build_parser().parse_args([*argv, "--help"])
    return buffer.getvalue()


class self_exit:
    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        return kind is SystemExit


class RunHelpTest(unittest.TestCase):
    def test_run_help_states_that_run_performs_steps(self):
        text = " ".join(help_of("run").split())
        self.assertIn("perform", text)
        for step in ("contract", "worktree", "implementation", "validation", "review", "candidate", "landing"):
            self.assertIn(step, text)
        self.assertIn("one JSON object", text)
        for stale in ("preview", "read-only"):
            self.assertNotIn(stale, text.lower())

    def test_top_level_listing_does_not_call_run_a_preview(self):
        text = " ".join(help_of().split())
        self.assertIn("perform the next bounded lifecycle step", text)
        self.assertNotIn("read-only run preview", text)

    def test_review_help_matches_the_shared_entry(self):
        text = " ".join(help_of("review").split())
        self.assertIn("runs the same step as cardine run", text)
        self.assertNotIn("read-only", text)

    def test_reference_does_not_call_run_a_preview(self):
        text = (ROOT / "docs" / "RUN_COMMANDS.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `cardine run "))
        self.assertIn("It is not a preview", row)


if __name__ == "__main__":
    unittest.main()
