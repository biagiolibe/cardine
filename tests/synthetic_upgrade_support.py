"""Synthetic migration fixtures; never load the framework's migration ledger.

The rich CLI scenarios reuse the current template vocabulary so their content
assertions remain useful. Release boundaries and operations belong to the test,
not to Meridian's release history. Small scenarios can supply their own files.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from cardine_cli_support import CardineCliFixtureMixin, ROOT
from cardine.templates import markers


class SyntheticFramework:
    def __init__(self, root: Path, version: str = "1.1.0", *, templates: dict[str, str] | None = None):
        self.root = root
        self.version = version
        (root / "migrations").mkdir(parents=True)
        (root / "capabilities").mkdir()
        if templates is None:
            shutil.copytree(ROOT / "templates", root / "templates")
            # Profile declarations and advisory rules are independent of migrations.
            for name in ("catalog-v1.json", "retired-text-v1.json"):
                shutil.copyfile(ROOT / "capabilities" / name, root / "capabilities" / name)
        else:
            for relative, content in templates.items():
                self.write("templates/workflows/" + relative, content)
            self.write_json("capabilities/catalog-v1.json", {
                "catalogVersion": 1, "capabilities": {}, "profiles": {},
            })
        self.write("VERSION", version + "\n")
        self.refresh_markers()

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_json(self, relative: str, content: object) -> None:
        self.write(relative, json.dumps(content, indent=2) + "\n")

    def refresh_markers(self, adoption_record: str = "001-synthetic-baseline") -> None:
        catalog_path = self.root / "capabilities/markers-v1.json"
        previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else {"capabilities": {}}
        catalog = {key: value for key, value in previous["capabilities"].items() if value["retired"]}
        baseline = {}
        for path in sorted((self.root / "templates").rglob("*.md")):
            entries = {}
            text = path.read_text(encoding="utf-8")
            for capability, version in markers.marker_pairs(text):
                block = markers.extract_marked_block(text, capability, version)
                entries[capability] = {"version": version, "sha256": markers.marker_block_sha256(block)}
                previous = catalog.get(capability, {}).get("requiredVersion", 0)
                catalog[capability] = {
                    "requiredVersion": max(previous, version), "required": True,
                    "retired": False, "adoptionRecord": adoption_record,
                }
            if entries:
                baseline[path.relative_to(self.root).as_posix()] = entries
        self.write_json("capabilities/markers-v1.json", {"catalogVersion": 1, "capabilities": catalog})
        self.write_json("capabilities/marker-baselines.json", baseline)

    def migration(self, identifier: str, target: str, *, capability: str | None = None,
                  version: int = 1, operation: str = "supersede", content: str | None = None,
                  paths: tuple[str, ...] = (), mode: str = "governed-sdd", **metadata: object) -> str:
        """Declare one transition, optionally installing its marked template text."""
        record = {
            "id": identifier, "from": self.version, "to": target,
            "description": "Synthetic " + operation, "managedPaths": list(paths),
            "verification": ["fixture assertions"], **metadata,
        }
        if capability:
            declaration = {"capability": capability, "capabilityVersion": version}
            if operation == "retire":
                record["removes"] = [declaration]
            else:
                record.update(declaration)
                if operation == "wrap":
                    record["wraps"] = [{"path": path, **declaration} for path in paths]
            if content is not None or operation == "retire":
                for path in paths:
                    relative = f"templates/workflows/{mode}/{path}"
                    destination = self.root / relative
                    text = destination.read_text(encoding="utf-8") if destination.exists() else ""
                    block = "" if operation == "retire" else (
                        f"<!-- MERIDIAN:BEGIN capability={capability} v{version} -->\n{content}\n<!-- MERIDIAN:END -->\n"
                    )
                    pattern = rf"<!-- MERIDIAN:BEGIN capability={re.escape(capability)} v\d+ -->.*?<!-- MERIDIAN:END -->\n?"
                    if re.search(pattern, text, re.DOTALL):
                        text = re.sub(pattern, lambda _: block, text, flags=re.DOTALL)
                    else:
                        text = text.rstrip() + "\n\n" + block
                    self.write(relative, text)
        self.write_json(f"migrations/{identifier}.json", record)
        if content is not None or operation == "retire":
            self.refresh_markers(identifier)
            if operation == "retire":
                catalog = json.loads((self.root / "capabilities/markers-v1.json").read_text())
                catalog["capabilities"][capability] = {
                    "requiredVersion": version, "required": False, "retired": True,
                    "adoptionRecord": identifier,
                }
                self.write_json("capabilities/markers-v1.json", catalog)
        self.version = target
        self.write("VERSION", target + "\n")
        return identifier


# Fixed test releases. 1.1.50 and 1.2.3 are CLI-only releases of 1.1.49
# and 1.1.55, respectively; before-closure reserves a label but adds no record.
RELEASES = (
    ("1.1.0", "baseline"), ("1.1.1", "merge"), ("1.1.2", "second-merge"),
    ("1.1.14", "before-insertion"), ("1.1.15", "insertion"),
    ("1.1.39", "before-host"), ("1.1.40", "host"), ("1.1.41", "restart"),
    ("1.1.42", "worktree"), ("1.1.43", "evidence"), ("1.1.44", "access"),
    ("1.1.47", "review"), ("1.1.48", "bounded"), ("1.1.49", "before-repair"),
    ("1.1.51", "repair"), ("1.1.53", "before-manual"), ("1.1.54", "manual"),
    ("1.1.55", "handoff"), ("1.2.3", "before-closure"), ("1.2.4", "lean-closure"),
    ("1.2.5", "governed-closure"), ("1.2.6", "adoption"), ("1.2.7", "wrapping"),
    ("1.2.8", "before-retirement"), ("1.2.9", "retirement"),
    ("1.2.11", "before-blueprint"), ("1.2.12", "blueprint"),
    ("1.2.15", "before-close"), ("1.3.0", "close"), ("1.4.0", "delivery"),
)
MIGRATIONS = {name: f"{index:03d}-synthetic-{name}" for index, (_, name) in enumerate(RELEASES, 1)}


def rich_upgrade_framework(root: Path) -> SyntheticFramework:
    fixture = SyntheticFramework(root, "1.0.0")
    paths = tuple(sorted({path.relative_to(workflow).as_posix()
                          for workflow in (root / "templates/workflows").iterdir()
                          for path in workflow.rglob("*.md")}))
    for target, name in RELEASES:
        if name == "before-closure":
            continue
        metadata = {}
        if name == "adoption":
            metadata["adoptExistingPaths"] = ["docs/WORKTREE_LIFECYCLE.md"]
        if name == "wrapping":
            metadata["wraps"] = [
                {"path": path, "capability": capability, "capabilityVersion": version}
                for path, capability, version in (
                    ("docs/WORKTREE_LIFECYCLE.md", "worktree-lifecycle", 6),
                    ("docs/PULL_REQUEST_POLICY.md", "remote-branch-cleanup", 1),
                )
            ]
        if name == "retirement":
            metadata["removes"] = [
                {"capability": "reasoning-budget-contract", "capabilityVersion": 1},
                {"capability": "role-scoped-agent-rules", "capabilityVersion": 1},
            ]
        # Preserve the cross-file declaration that the per-file verification
        # regression exercises: lifecycle-orchestration touches the context
        # policy without having a marker in that file.
        capability = {"baseline": "review-remediation-record", "merge": "lifecycle-orchestration"}.get(name)
        fixture.migration(MIGRATIONS[name], target, capability=capability, paths=paths, **metadata)
    fixture.refresh_markers(MIGRATIONS["delivery"])
    fixture.write("VERSION", "1.1.0\n")
    return fixture


class SyntheticUpgradeFixtureMixin(CardineCliFixtureMixin):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        self.fixture = rich_upgrade_framework(self.framework)
        self.project.mkdir()
        self.copy_governed_templates()

    def _assert_upgrade_installs_closure_command_policy(self, mode: str) -> None:
        workflow = self.framework / f"templates/workflows/{mode}"
        relative = ".codex/rules/meridian.rules"
        current = (workflow / relative).read_text(encoding="utf-8")
        previous = re.sub(r"\n# Unattended-closure additions.*?\[\"ls\", [^\n]*\n", "\n", current, flags=re.DOTALL)
        self.assertNotEqual(previous, current)
        (workflow / relative).write_text(previous, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", mode).returncode, 0)
        local = 'prefix_rule(pattern=["project-tool", "run"], decision="allow")\n'
        rules = self.project / relative
        rules.write_text(rules.read_text(encoding="utf-8") + "\n# Local rule\n" + local, encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 022-synthetic-adoption", checked.stdout)
        if mode == "governed-sdd":
            lifecycle_plan = next(
                line
                for line in checked.stdout.splitlines()
                if "docs/WORKTREE_LIFECYCLE.md" in line
            )
            self.assertEqual(lifecycle_plan.split()[0], "KEEP")
            self.assertNotIn("ADOPT", lifecycle_plan)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = rules.read_text(encoding="utf-8")
        self.assertIn('["meridian", "worktree", ["evidence", "closure-status", "advance"]]', upgraded)
        self.assertIn('prefix_rule(pattern=["git", "mv"], decision="allow")', upgraded)
        self.assertIn(local, upgraded)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.6")
        self.assertEqual(manifest["appliedMigrations"][-1], "022-synthetic-adoption")

