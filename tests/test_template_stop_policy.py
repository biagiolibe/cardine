"""Keep shipped stop instructions aligned with registry decision authority."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"


def stops_section() -> str:
    text = (ROOT / "templates/single/PROJECT_WORKFLOW.md").read_text()
    match = re.search(
        r"<!-- CARDINE:BEGIN capability=git-workflow v\d+ -->(.*?)<!-- CARDINE:END -->", text, re.S,
    )
    return re.split(r"\n##+ Stops and denials\n", match[1])[1]


class TemplateStopPolicyTest(unittest.TestCase):
    def test_decision_12_distinguishes_guardrails_recovery_and_failing_work(self):
        policy = " ".join(stops_section().split())
        for instruction in (
            # Guardrail: only a blocked outcome that needs a person is a stop.
            "Stop only for a denied action, a scope change, or `outcome: blocked` with `stop.human_decision: true`",
            "report the code and `stop.resume`",
            # Recoverable state: act in the same turn.
            "Every other outcome is not a stop: run `next.command` in the same turn",
            "wait `retry_after_seconds` when `waiting`",
            # Failing work: repair and rerun; the engine counts.
            "Failing validation is work on the task: fix it and call `cardine run` again",
            "The engine reruns once, records an intermittent pass, and counts failures",
            "after the task's `validationRetryLimit` counted failures it stops with `VALIDATION_RETRY_LIMIT`",
            "Record no counter yourself",
        ):
            self.assertIn(instruction, policy)

    def test_named_codes_exist_and_guardrails_require_a_person(self):
        entries = {
            entry["code"]: entry
            for entry in json.loads(
                (ROOT / "capabilities/stop-codes-v1.json").read_text()
            )["stops"]
        }
        policy = stops_section()
        codes = set(re.findall(r"`(" + TOKEN + r")`|BLOCKED (" + TOKEN + r")", policy))
        named = {left or right for left, right in codes}
        self.assertTrue(named)
        self.assertFalse(named - entries.keys())
        # Every code the section names is one the agent stops on, so each needs a person.
        for code in named:
            self.assertIs(entries[code]["human_decision"], True, code)
        self.assertIs(entries["VALIDATION_FAILED"]["human_decision"], False)
        self.assertNotIn("VALIDATION_FAILED", policy)

    def test_the_git_workflow_block_ships_once_in_the_workflow(self):
        carriers = [
            path.name for path in (ROOT / "templates/single").rglob("*.md")
            if "capability=git-workflow" in path.read_text()
        ]
        self.assertEqual(carriers, ["PROJECT_WORKFLOW.md"])


if __name__ == "__main__":
    unittest.main()
