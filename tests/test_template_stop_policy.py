"""Keep shipped stop instructions aligned with registry decision authority."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"


class TemplateStopPolicyTest(unittest.TestCase):
    def test_named_codes_exist_and_guardrails_require_a_person(self):
        entries = {
            entry["code"]: entry
            for entry in json.loads(
                (ROOT / "capabilities/stop-codes-v1.json").read_text()
            )["stops"]
        }
        policies = []
        for path in (ROOT / "templates/workflows").rglob("*.md"):
            text = path.read_text()
            match = re.search(
                r"<!-- MERIDIAN:BEGIN capability=git-workflow v\d+ -->(.*?)<!-- MERIDIAN:END -->",
                text, re.S,
            )
            if not match:
                continue
            policies.append(path)
            policy = match[1]
            codes = set(re.findall(r"`(" + TOKEN + r")`|BLOCKED (" + TOKEN + r")", re.split(r"\n##+ Stops and denials\n", policy)[1]))
            named = {left or right for left, right in codes}
            with self.subTest(path=str(path)):
                self.assertTrue(named)
                self.assertFalse(named - entries.keys())
                guardrail = re.search(r"- \*\*Guardrail\.\*\*(.*?)(?=\n- )", policy, re.S)
                self.assertIsNotNone(guardrail)
                guardrail_codes = set(re.findall(r"BLOCKED (" + TOKEN + r")", guardrail[1]))
                # Explicit stop instructions outside the class paragraph also
                # declare guardrails, including required review and rule conflict.
                guardrail_codes.update(re.findall(
                    r"stop (?:with|at) `(?:BLOCKED )?(" + TOKEN + r")`", policy
                ))
                self.assertTrue(guardrail_codes)
                for code in guardrail_codes:
                    self.assertIs(entries[code]["human_decision"], True, code)
                self.assertIs(entries["VALIDATION_FAILED"]["human_decision"], False)
        self.assertEqual(len(policies), 4)
