"""Prevent retired product identifiers from returning outside declared surfaces."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OLD = "meri" + "dian"
INSTALLATION_TAG = OLD.upper() + "-INSTALLATION-CHECK"
OLD_NAME_TAG = OLD.upper() + "-OLD-NAME-TEST"
TEMPLATE_TAG = OLD.upper() + "-TEMPLATE-PROGRAM"
HISTORIC_PROFILE = "meridian-worktrees"


@dataclass(frozen=True)
class Allowance:
    group: int
    removal: str
    paths: str
    pattern: str | None = None
    tag: str | None = None


# One table: path exemptions cover only declared surfaces; content exemptions
# cover the matched identifier, never an unrelated occurrence on the same line.
# OLD is composed above so the guard can inspect its own definitions as well.
ALLOWLIST = (
    Allowance(
        1, "kept: guard test pathname only",
        re.escape("tests/" + Path(__file__).name),
        r"^<path>$",
    ),
    Allowance(
        2, "9",
        r"(?:skills|commands|\.claude-plugin)/.*",
    ),
    Allowance(
        2, "9",
        r"templates/single/\.codex/rules/" + OLD + r"\.rules",
    ),
    Allowance(
        2, "9",
        r"(?:src|tests)/.*",
        OLD.upper() + r":(?:BEGIN|END|\(\?:BEGIN\|END\))(?:\s+|\\s\+)(?:worktree-permissions|codex-user-rules)\b",
    ),
    Allowance(
        2, "10",
        r"tests/fixtures/task-blueprint-v15\.md",
    ),
    # Exact legacy migration expressions; never a current profile declaration.
    Allowance(2, "9", r"src/cardine/hosts/codex\.py",
              r'^\s*legacy_name = "' + OLD + r'-worktrees"$'),
    Allowance(2, "9", r"src/cardine/hosts/codex\.py",
              r"^PREVIOUS_CODEX_USER_RULES = LEGACY_CODEX_USER_RULES\.replace\('# " + OLD.upper() + r":', '# CARDINE:'\)$"),
    Allowance(2, "9", r"src/cardine/hosts/codex\.py",
              r'^\s*elif legacy_path and "# ' + OLD.upper() + r':" in legacy_text and "codex-user-rules" in legacy_text:$'),
    Allowance(2, "9", r"src/cardine/hosts/codex\.py",
              r'^\s*\.replace\("Cardine-managed", "' + OLD.capitalize() + r'-managed"\)\)$'),
    Allowance(2, "9", r"src/cardine/hosts/codex\.py",
              r'^\s*proposed, "migrate the owned ' + OLD.capitalize() + r' profile", text\)$'),
    Allowance(2, "9", r"tests/test_(?:codex_user_rules|host_codex_repair)\.py",
              r"^\s*\.replace\(['\"]CARDINE:['\"], ['\"]" + OLD.upper() + r":['\"]\)\s*$"),
    Allowance(2, "9", r"tests/test_codex_user_rules\.py",
              r"^\s*\.replace\('cardine-worktrees', '" + OLD + r"-worktrees'\)$"),
    Allowance(2, "9", r"tests/test_(?:codex_user_rules|host_codex_repair)\.py",
              r"^\s*\.replace\(['\"]Cardine-managed['\"], ['\"]" + OLD.capitalize() + r"-managed['\"]\)\)$"),
    Allowance(2, "9", r"tests/test_host_codex_repair\.py",
              r'^\s*\.replace\("cardine-worktrees", "' + OLD + r'-worktrees"\)$|^\s*self\.assertNotIn\(\'' + OLD + r'-worktrees\', actual\)$'),
    Allowance(2, "9", re.escape("tests/" + Path(__file__).name),
              r'^HISTORIC_PROFILE = "' + OLD + r'-worktrees"$'),
    Allowance(
        2, "9",
        r"(?:src|tests|capabilities)/.*",
        OLD + r"\.rules\b",
    ),
    Allowance(
        2, "9",
        r"(?:src|scripts|tests|docs)/.*",
        OLD + r"-(?:lean-delivery|governed-sdd)(?:-claude-code)?\b",
    ),
    Allowance(
        2, "9",
        r"(?:src|scripts|tests|docs)/.*",
        r"(?:commands/|/)?" + OLD + r"-(?:init|task|upgrade|audit)\b",
    ),
    Allowance(
        2, "9",
        r"src/cardine/hosts/skills\.py",
        OLD + r"-\*",
    ),
    Allowance(
        2, "9",
        r"(?:src/cardine/hosts/claude|tests/test_host_worktree_setup)\.py",
        r"(?:\"" + OLD + r"\"|" + OLD + r"@local)",
    ),
    Allowance(
        2, "9",
        r"(?:src/cardine/release/update|scripts/(?:release|upgrade_project)|tests/test_(?:release_self_check|self_update))\.(?:py|sh)",
        r"(?:biagiolibe/|extraKnownMarketplaces\.|cache/|marketplace update |get\(\"|\{\")" + OLD + r"\b",
    ),
    Allowance(
        2, "9",
        r"(?:scripts/(?:check_repository|align_queue)|tests/(?:cardine_cli_support|synthetic_upgrade_support|test_(?:codex_rules|codex_worktree_hooks|codex_read_guard|execution_evidence|integration_projections|stop_audit|template_marker_heading|cardine_upgrade_lifecycle)))\.py",
        OLD + r'''(?=\s+(?:worktree|execution|locations|audit|upgrade|adopt|review|codex|task|hook|Reviewer-Integrator)|["'][,\n\)])''',
    ),
    Allowance(
        2, "9",
        r"tests/test_check_repository\.py",
        r'"name": "' + OLD + r'"',
    ),
    Allowance(
        2, "9",
        r"tests/program_word_support\.py",
        re.escape(TEMPLATE_TAG) + r"\b|(?<![\w./-])" + OLD + r"(?![\w./-])",
        tag=TEMPLATE_TAG,
    ),
    Allowance(
        3, "10",
        r"(?:AGENTS\.md|CLAUDE\.md|LANGUAGE_POLICY\.md|PROJECT_WORKFLOW\.md|docs/(?:COMPLETION_REPORT_TEMPLATE|CONTEXT_BUDGET_POLICY|EXECUTION_EVIDENCE_PROFILE|WORKTREE_LIFECYCLE)\.md|\.codex/(?:hooks\.json|rules/" + OLD + r"\.rules)|hooks/(?:hooks\.json|queue-briefing\.sh|read-guard\.sh))",
    ),
    Allowance(
        3, "10",
        r"\." + OLD + r"/.*",
    ),
    Allowance(
        6, "kept: Cardine baselines and manifest name the rules template until it is renamed",
        r"\.cardine/baselines/[^/]+/\.codex/rules/" + OLD + r"\.rules",
    ),
    Allowance(
        6, "kept: Cardine baselines and manifest name the rules template until it is renamed",
        r"\.cardine/manifest\.json",
        r"\.codex/rules/" + OLD + r"\.rules",
    ),
    Allowance(
        6, "kept: task state repeats record paths and titles, like the records of group 4",
        r"\.cardine/tasks/[^/]+\.json",
    ),
    Allowance(
        6, "kept: the evidence ledger records validation commands and their output, which name the guard module",
        r"\.cardine/evidence/[^/]+\.json",
    ),
    Allowance(
        3, "10",
        r"\.codex/rules/local\.rules",
        r"^# (?:Project-local command approval additions for the " + OLD.capitalize() + r" task lifecycle\.|Kept outside the managed " + OLD + r"\.rules copy so `" + OLD + r" upgrade` does not|see drift\. Rules combine with " + OLD + r"\.rules and the most restrictive|Lifecycle commands that " + OLD + r"\.rules does not list yet\.)$",
    ),
    Allowance(
        3, "10",
        r"\.codex/rules/local\.rules",
        r'prefix_rule\(pattern=\["' + OLD + r'", "worktree", \["evidence", "closure-status", "advance"\]\], decision="allow"\)',
    ),
    Allowance(
        4, "kept: historical records; remove or narrow in work item 10 when this repository moves to Cardine and records stop naming installed " + OLD.capitalize(),
        r"(?:tasks/(?:done|handoffs)/.*|tasks/(?:QUEUE[^/]*|TASK_BLUEPRINT|[0-9]{3}(?:-[^/]+)?)\.md|PROJECT_PLAN\.md|CHANGELOG\.md|changelog\.d/.*|releases/.*|\.github/.*|README\.md|CONTRIBUTING\.md|WORKFLOW_GUIDE\.md|SECURITY\.md|CODE_OF_CONDUCT\.md|migrations/README\.md|tests/fixtures/release-[^/]+/.*)",
    ),
    Allowance(
        4, "kept: historical design and guides; guides replaced by 11",
        r"docs/(?:ADR_[^/]+\.md|AGENT_OPERATIONS\.md|CLEAN_INSTALL_VERIFICATION\.md|CONSUMER_PROFILES\.md|CONSUMER_ROUTER_ADOPTION_PLAYBOOK\.md|DISTRIBUTION_AND_UPDATE_DESIGN\.md|GOVERNED_WORKFLOW\.md|HOST_CAPABILITY_CONTRACT\.md|HOW_TO_UPGRADE\.md|" + OLD.upper() + r"_SELF_HOSTING_PROFILE\.md|MODULE_SPLIT_PLAN\.md|PLATFORM_SUPPORT\.md|BENCHMARK_PROTOCOL\.md|RUN_ENGINE_PLAN\.md|HOST_INTEGRATION_PLAN\.md|CONVERSION_PLAN\.md|RELEASE_PLAN\.md|DOCUMENTATION_PLAN\.md|SINGLE_SOURCE_OF_TRUTH_PLAN\.md|RULE_ENFORCEMENT_INVENTORY\.md|FORGERY_INVENTORY\.md|STOP_REVIEW\.md|TEXT_GATE_INVENTORY\.md|PROJECT_DECLARATION\.md|QUICKSTART\.md|RENAME_PLAN\.md|SINGLE_WORKFLOW_PLAN\.md|TASK_IDENTITY_POLICY\.md|assets/.*)",
    ),
    Allowance(
        5, "10",
        r"src/cardine/legacy/(?:" + OLD + r"_installation|" + OLD + r"_locations|snapshot|conversion_reader)\.py",
    ),
    Allowance(
        5, "kept: the conversion package, while adopt exists (DD2)",
        r"(?:src/cardine/adopt/.*|tests/test_adopt_[^/]*)\.py",
    ),
    Allowance(
        5, "10",
        r"tests/test_legacy_" + OLD + r"_installation\.py",
    ),
    Allowance(
        5, "10",
        r"tests/(?:test_(?:legacy_marker_syntax|status_legacy_boundary|conversion_reader)|conversion_fixture)\.py",
    ),
    Allowance(
        5, "10",
        r"(?:src|scripts|tests)/.*\.py",
        tag=INSTALLATION_TAG,
    ),
    Allowance(
        5, "10: remove or retarget negative tests with reader",
        r"tests/.*\.py",
        tag=OLD_NAME_TAG,
    ),
)


def scan_repository(root: Path, allowlist=ALLOWLIST) -> tuple[list[str], Counter]:
    """Return forbidden identifiers and usage counts, including stale allowances."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root, check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    used = Counter()
    present = set()
    failures = []
    compiled = [(re.compile(entry.paths), re.compile(entry.pattern) if entry.pattern else None)
                for entry in allowlist]

    def inspect(path: str, line_number: int, line: str, previous: str = "") -> None:
        for occurrence in re.finditer(OLD, path if line_number == 0 else line, re.IGNORECASE):
            allowed = False
            for index, entry in enumerate(allowlist):
                paths, pattern = compiled[index]
                if not paths.fullmatch(path):
                    continue
                if entry.tag is not None:
                    matches = entry.tag in line or entry.tag in previous
                    if matches and pattern is not None:
                        matches = any(match.start() <= occurrence.start() and match.end() >= occurrence.end()
                                      for match in pattern.finditer(line))
                elif pattern is None:
                    matches = True
                elif line_number == 0:
                    matches = pattern.fullmatch("<path>") is not None
                else:
                    matches = any(match.start() <= occurrence.start() and match.end() >= occurrence.end()
                                  for match in pattern.finditer(line))
                if matches:
                    used[index] += 1
                    allowed = True
            if not allowed:
                failures.append(f"{path}:{line_number}: {line.strip()}")

    for name in sorted(set(listed) - {""}):
        path = root / name
        if not path.is_file():
            continue
        present.update(index for index, (paths, _) in enumerate(compiled) if paths.fullmatch(name))
        inspect(name, 0, "<path>")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            inspect(name, number, line, lines[number - 2] if number > 1 else "")
    for index, entry in enumerate(allowlist):
        if not used[index] and (entry.group not in (3, 5, 6) or index in present):
            failures.append(f"unused allowlist entry {index}: group {entry.group}, {entry.removal}, {entry.paths}")
    return failures, used


class IdentifierGuardTest(unittest.TestCase):
    def test_conditional_allowances_require_use_only_when_a_matching_file_exists(self):
        with tempfile.TemporaryDirectory(prefix="cardine-conditional-guard-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for group in (3, 5, 6):
                with self.subTest(group=group):
                    allowance = Allowance(group, "10", r"retired/.*\.py", OLD)
                    path = root / "retired/example.py"
                    path.parent.mkdir(exist_ok=True)
                    self.assertEqual(scan_repository(root, (allowance,))[0], [])
                    path.write_text(OLD + "\n")
                    self.assertEqual(scan_repository(root, (allowance,))[0], [])
                    path.write_text("Cardine\n")
                    self.assertTrue(any("unused allowlist entry" in failure
                                        for failure in scan_repository(root, (allowance,))[0]))
                    path.unlink()
                    self.assertEqual(scan_repository(root, (allowance,))[0], [])
            stale = Allowance(2, "9", r"missing/.*")
            self.assertTrue(any("unused allowlist entry" in failure
                                for failure in scan_repository(root, (stale,))[0]))

    def test_repository_has_no_unallowed_identifiers_or_stale_allowances(self):
        failures, _ = scan_repository(ROOT)
        self.assertEqual(failures, [], "\n".join(failures))

    def test_historical_profile_is_allowed_only_in_the_migration_expression(self):
        allowance = next(entry for entry in ALLOWLIST if entry.paths == r"src/cardine/hosts/codex\.py"
                         and entry.pattern and "legacy_name" in entry.pattern)
        with tempfile.TemporaryDirectory(prefix="cardine-profile-guard-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            path = root / "src/cardine/hosts/codex.py"
            path.parent.mkdir(parents=True)
            path.write_text(f'    legacy_name = "{HISTORIC_PROFILE}"\n')
            self.assertEqual(scan_repository(root, (allowance,))[0], [])
            for line in (f'CODEX_PERMISSION_PROFILE = "{HISTORIC_PROFILE}"',
                         f'default_permissions = "{HISTORIC_PROFILE}"',
                         f'    current_profile = "{HISTORIC_PROFILE}"'):
                with self.subTest(line=line):
                    path.write_text(line + "\n")
                    failures, _ = scan_repository(root, (allowance,))
                    self.assertTrue(any("codex.py:1:" in failure for failure in failures))
            path.unlink()
            other = root / "src/cardine/shared/models.py"
            other.parent.mkdir(parents=True)
            other.write_text(f'CODEX_PERMISSION_PROFILE = "{HISTORIC_PROFILE}"\n')
            failures, _ = scan_repository(root, (allowance,))
            self.assertTrue(any("models.py:1:" in failure for failure in failures))

    def test_future_task_records_pass_without_allowing_other_paths(self):
        allowance = next(e for e in ALLOWLIST if e.removal.startswith("kept: historical records"))
        with tempfile.TemporaryDirectory(prefix="cardine-task-record-guard-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            record = root / "tasks/999-future-record.md"
            record.parent.mkdir()
            record.write_text(OLD + "\n")
            # Cardine names a record by its ID alone.
            (root / "tasks/998.md").write_text(OLD + "\n")
            self.assertEqual(scan_repository(root, (allowance,))[0], [])
            for name in (
                "tasks/notes.md", "tasks/99-short-id.md", "tasks/1000-long-id.md",
                "tasks/999-.md", "tasks/999-nested/record.md", "tasks/999-record.txt",
                "src/cardine/example.py", "templates/example.md", "tests/test_example.py",
            ):
                with self.subTest(path=name):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(OLD + "\n")
                    failures, _ = scan_repository(root)
                    self.assertIn(f"{name}:1: {OLD}", failures)
                    path.unlink()

    def test_seeded_group_one_identifier_fails_in_temporary_repository(self):
        with tempfile.TemporaryDirectory(prefix="cardine-identifier-guard-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            # Check tracked content, untracked paths and content, case folding,
            # and a forbidden identifier next to a permitted marker.
            tracked = root / "src/cardine/example.py"
            tracked.parent.mkdir(parents=True)
            tracked.write_text('TITLE = "Cardine"\n')
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            self.assertEqual(scan_repository(root, ())[0], [])
            marker_allowance = Allowance(2, "9", r"src/.*", OLD.upper() + r":BEGIN")
            for text in (OLD.capitalize(), OLD.upper(), OLD.upper() + ":BEGIN " + OLD):
                tracked.write_text(text + "\n")
                failures, _ = scan_repository(root, (marker_allowance,))
                self.assertTrue(any(str(tracked.relative_to(root)) + ":1:" in f for f in failures))
            helper = root / "tests/program_word_support.py"
            helper.parent.mkdir()
            helper_allowance = next(e for e in ALLOWLIST if e.tag == TEMPLATE_TAG)
            helper.write_text("# " + TEMPLATE_TAG + "\n" + OLD + " ." + OLD + "/tasks\n")
            failures, _ = scan_repository(root, (helper_allowance,))
            self.assertTrue(any(helper.name + ":2:" in f for f in failures))
            helper.unlink()
            tracked.write_text("Cardine\n")
            untracked = root / (OLD + ".txt")
            untracked.write_text(OLD)
            failures, _ = scan_repository(root, ())
            self.assertTrue(any(untracked.name + ":0:" in f for f in failures))
            self.assertTrue(any(untracked.name + ":1:" in f for f in failures))
            (root / ".gitignore").write_text("*.txt\n")
            self.assertEqual(scan_repository(root, ())[0], [])
            failures, _ = scan_repository(root, (Allowance(2, "9", "missing/.*"),))
            self.assertTrue(any("unused allowlist entry" in f for f in failures))


if __name__ == "__main__":
    unittest.main()
