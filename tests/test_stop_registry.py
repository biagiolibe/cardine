"""RE2b last-emitter audit, including dynamic routing and shipped judgments."""

import ast
import unittest
from pathlib import Path

import cardine_cli_support  # Initialize the source import path.
from cardine.stops.registry import load_stop_registry

ROOT = Path(__file__).resolve().parents[1]
RETIRED = {"REVIEW_REQUIRED", "REVIEW_STALE", "WORKFLOW_UNREADABLE", "EXECUTION_PROFILE_MISSING", "SELF_UPDATE_NON_FF"}


class StopRegistryTest(unittest.TestCase):
    def test_retired_codes_have_no_static_dynamic_or_judgment_emitter(self):
        registry = load_stop_registry()
        self.assertFalse(RETIRED & registry.keys())
        for directory in ("src/cardine", "templates/single"):
            for path in (ROOT / directory).rglob("*"):
                if path.suffix not in {".py", ".md", ".json"}:
                    continue
                text = path.read_text()
                with self.subTest(path=str(path)):
                    for code in RETIRED:
                        self.assertNotIn(code, text)
        # Replacement emitter-to-cause inventory. Count all literals, including
        # the closure report's keyword argument (not only direct stop calls).
        expected = {
            ("src/cardine/tasks/contract.py", "UNDECLARED_VALIDATION_COMMANDS"): 1,  # execution-profile
            ("src/cardine/integration/evidence.py", "UNDECLARED_VALIDATION_COMMANDS"): 1,  # candidate policy
            ("src/cardine/integration/merge.py", "UNDECLARED_VALIDATION_COMMANDS"): 1,  # candidate policy
            ("src/cardine/lifecycle/closure.py", "UNDECLARED_VALIDATION_COMMANDS"): 1,  # dynamic report
            ("src/cardine/integration/merge.py", "REVIEW_NOT_APPROVED"): 4,  # missing verdict/issued decision, stale ancestor/tree
            ("src/cardine/review/verdict.py", "REVIEW_NOT_APPROVED"): 3,  # missing issued session, stale issued inputs/submission
        }
        found = {}
        for path in (ROOT / "src/cardine").rglob("*.py"):
            if "stops" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and node.value in {
                    "UNDECLARED_VALIDATION_COMMANDS", "REVIEW_NOT_APPROVED", "RULE_CONFLICT"
                }:
                    key = (path.relative_to(ROOT).as_posix(), node.value)
                    found[key] = found.get(key, 0) + 1
        self.assertEqual(found, expected)
        # Dynamic stop factories remain covered by RE2a's full emitter audit;
        # judgment emitters are covered by the shipped-template audit below.
        from test_run_recovery import scan_emitters
        from cardine.stops.causes import EMITTER_CAUSES
        self.assertEqual(scan_emitters(), set(EMITTER_CAUSES))

    def test_consolidated_negatives_keep_human_authority_and_cause_detail(self):
        registry = load_stop_registry()
        for code in ("REVIEW_NOT_APPROVED", "UNDECLARED_VALIDATION_COMMANDS", "RULE_CONFLICT"):
            entry = registry[code]
            self.assertEqual((entry["resolution"], entry["human_decision"]), ("guardrail", True))
        self.assertIn("missing or stale", registry["REVIEW_NOT_APPROVED"]["summary"])
        self.assertIn("missing-policy", registry["RULE_CONFLICT"]["summary"])
        self.assertIn("execution-profile", registry["UNDECLARED_VALIDATION_COMMANDS"]["summary"])

