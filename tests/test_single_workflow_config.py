"""Project presets resolve independently of human-authored workflow assets."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cardine.shared.errors import CardineError
from cardine.shared.project import (
    parse_project_declaration, project_validation_commands, resolve_project_configuration,
)
from cardine.templates.mode import detect_mode, resolve_preset
from project_config_support import write_project_config


class SingleWorkflowConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)

    def declaration(self, **fields):
        return {"version": 1, "preset": "lean", **fields}

    def validation(self):
        return {"commands": {"repo": "python3 check.py", "suite": "python3 suite.py"},
                "baseline": ["repo"],
                "candidate": {"REUSE": [], "BOUNDED": ["repo"], "FULL": ["suite"]}}

    def test_preset_defaults_and_explicit_overrides(self):
        for preset in ("lean", "governed"):
            with self.subTest(preset=preset):
                write_project_config(self.project, preset)
                resolved = resolve_project_configuration(self.project)
                governed = preset == "governed"
                self.assertEqual(resolved["taskDefaults"], {
                    "review": "required" if governed else "not_required",
                    "authorityRequired": governed, "expectedCodeSurfaceRequired": governed,
                    "validationRetryLimit": 3, "landingMode": "direct", "ciBeforeLanding": False})
                self.assertEqual(resolved["taskIdentity"], {"mode": "opaque"})
                overrides = {"review": "not_required" if governed else "required",
                             "authorityRequired": not governed,
                             "expectedCodeSurfaceRequired": not governed, "validationRetryLimit": 1}
                write_project_config(self.project, preset, taskDefaults=overrides)
                resolved = resolve_project_configuration(self.project)
                for key, value in overrides.items():
                    self.assertEqual(resolved["taskDefaults"][key], value)

    def test_parse_preserves_omission_and_explicit_false(self):
        declaration = self.declaration(taskDefaults={"authorityRequired": False})
        self.assertEqual(parse_project_declaration(declaration), declaration)
        self.assertNotIn("review", declaration["taskDefaults"])
        parse_project_declaration(self.declaration(taskDefaults={}))

    def test_invalid_types_and_unknown_properties_fail_closed(self):
        invalid = [None, [], {}, {"version": True, "preset": "lean"},
                   self.declaration(preset=None), self.declaration(preset=[]),
                   self.declaration(preset="LEAN_DELIVERY"), self.declaration(unknown=True),
                   self.declaration(taskDefaults=None), self.declaration(taskDefaults={"unknown": 1}),
                   self.declaration(taskIdentity=None), self.declaration(taskIdentity={"mode": "other"}),
                   self.declaration(taskIdentity={"unknown": True})]
        for key, values in {
            "review": [False, "optional", []], "authorityRequired": [0, "false", None],
            "expectedCodeSurfaceRequired": [1, None], "validationRetryLimit": [True, 0, -1, 1.5, "3"],
            "landingMode": [None, "pull-request", "other"], "ciBeforeLanding": [0, "true"],
        }.items():
            invalid.extend(self.declaration(taskDefaults={key: value}) for value in values)
        for declaration in invalid:
            with self.subTest(declaration=declaration), self.assertRaises(CardineError):
                parse_project_declaration(declaration)

    def test_direct_only_never_probes_a_forge(self):
        with patch("subprocess.run", side_effect=AssertionError("forge probe")):
            parse_project_declaration(self.declaration(taskDefaults={"landingMode": "direct"}))
            with self.assertRaisesRegex(CardineError, "only direct"):
                parse_project_declaration(self.declaration(taskDefaults={"landingMode": "pull-request"}))

    def test_ci_consistency(self):
        for ci in (None, "none", {}, {"provider": "github", "requiredChecks": []},
                   {"provider": "gitlab", "requiredChecks": ["test"]}):
            declaration = self.declaration(taskDefaults={"ciBeforeLanding": True})
            if ci is not None:
                declaration["ci"] = ci
            with self.subTest(ci=ci), self.assertRaises(CardineError):
                parse_project_declaration(declaration)
        parse_project_declaration(self.declaration(taskDefaults={"ciBeforeLanding": True},
                                  ci={"provider": "github", "requiredChecks": ["test"]}))
        parse_project_declaration(self.declaration(ci="none", taskDefaults={"ciBeforeLanding": False}))
        with self.assertRaises(CardineError):
            parse_project_declaration(self.declaration(ci=None))

    def test_validation_composes_baseline_and_candidate(self):
        configuration = self.declaration(validation=self.validation())
        parse_project_declaration(configuration)
        self.assertEqual(project_validation_commands(configuration), ("python3 check.py",))
        for outcome in ("REUSE", "BOUNDED"):
            self.assertEqual(project_validation_commands(configuration, outcome),
                             ("python3 check.py", "git diff --check"))
        self.assertEqual(project_validation_commands(configuration, "FULL"),
                         ("python3 check.py", "python3 suite.py", "git diff --check"))
        with self.assertRaises(CardineError):
            project_validation_commands(configuration, "UNKNOWN")

    def test_validation_requires_unique_known_command_references(self):
        for key, value in (("baseline", ["unknown"]), ("baseline", ["repo", "repo"]),
                           ("baseline", "repo"), ("baseline", [{}]), ("commands", {"": "true"}),
                           ("commands", {"repo": " "}), ("commands", {"repo": True}),
                           ("candidate", {"REUSE": [], "BOUNDED": []}),
                           ("candidate", {"REUSE": [], "BOUNDED": [], "FULL": ["unknown"]}),
                           ("candidate", {"REUSE": [], "BOUNDED": [], "FULL": ["repo", "repo"]})):
            validation = self.validation()
            validation[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(CardineError):
                parse_project_declaration(self.declaration(validation=validation))
        for validation in (None, {}, {**self.validation(), "unknown": True}):
            with self.subTest(validation=validation), self.assertRaises(CardineError):
                parse_project_declaration(self.declaration(validation=validation))

    def test_explicit_empty_validation_is_different_from_absent(self):
        empty = {"commands": {}, "baseline": [],
                 "candidate": {"REUSE": [], "BOUNDED": [], "FULL": []}}
        configuration = self.declaration(validation=empty)
        before = copy.deepcopy(configuration)
        self.assertEqual(parse_project_declaration(configuration), before)
        self.assertEqual(project_validation_commands(configuration), ())
        self.assertEqual(project_validation_commands(configuration, "FULL"), ("git diff --check",))
        with self.assertRaisesRegex(CardineError, "requires validation"):
            project_validation_commands(self.declaration())

    def test_task_identity_modes(self):
        for identity in ({}, {"mode": "opaque"}, {"mode": "milestone"}):
            write_project_config(self.project, taskIdentity=identity)
            self.assertEqual(resolve_project_configuration(self.project)["taskIdentity"],
                             {"mode": identity.get("mode", "opaque")})

    def test_configuration_is_independent_of_workflow_and_queue(self):
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY GOVERNED_SDD\n")
        (self.project / "tasks").mkdir()
        (self.project / "tasks/QUEUE.md").write_text("| Order | ID | Status | Review |\n")
        original = Path.read_text

        def read(path, *args, **kwargs):
            self.assertEqual(path.name, "project.json", f"unexpected workflow read: {path}")
            return original(path, *args, **kwargs)

        for preset, mode in (("lean", "lean-delivery"), ("governed", "governed-sdd")):
            write_project_config(self.project, preset)
            with patch.object(Path, "read_text", read):
                self.assertEqual(resolve_preset(self.project), preset)
                self.assertEqual(detect_mode(self.project), mode)
        (self.project / "PROJECT_WORKFLOW.md").unlink()
        (self.project / "tasks/QUEUE.md").write_text("")
        self.assertEqual(detect_mode(self.project), "governed-sdd")

    def test_missing_and_malformed_configuration_are_errors(self):
        with self.assertRaisesRegex(CardineError, "missing project configuration"):
            detect_mode(self.project)
        path = self.project / ".cardine/project.json"
        path.parent.mkdir()
        for content in ("{", "[]", '{"version": 1}', '{"version": 1, "preset": "other"}'):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(CardineError):
                detect_mode(self.project)
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(CardineError, "invalid project declaration"):
            detect_mode(self.project)

    def test_existing_locations_and_scoping_are_preserved(self):
        declaration = self.declaration(locations={"queue": "docs/QUEUE.md", "taskRoots": ["tasks"]},
                                       validationScoping=[{"paths": ["docs/**"], "commands": ["check docs"]}])
        self.assertEqual(parse_project_declaration(declaration), declaration)
        for path in ("../outside", "/outside"):
            with self.assertRaises(CardineError):
                parse_project_declaration(self.declaration(locations={"queue": path}))

    def test_schema_declares_closed_policy_objects(self):
        schema = json.loads((ROOT / "schemas/project-v1.schema.json").read_text())
        self.assertEqual(schema["required"], ["version", "preset"])
        for key in ("taskDefaults", "taskIdentity", "validation"):
            self.assertFalse(schema["properties"][key]["additionalProperties"])
        self.assertEqual(schema["properties"]["preset"]["enum"], ["lean", "governed"])


if __name__ == "__main__":
    unittest.main()
