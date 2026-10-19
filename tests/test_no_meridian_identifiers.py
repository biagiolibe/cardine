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
        2, "5b",
        r"(?:(?:templates|skills|commands|\.claude-plugin)/.*|capabilities/(?:markers-v1|marker-baselines|retired-text-v1)\.json)",
    ),
    Allowance(
        2, "5b",
        r"tests/fixtures/task-blueprint-v15\.md",
    ),
    Allowance(
        2, "5b",
        r"(?:src|scripts|tests|docs)/.*",
        OLD.upper() + r":(?:BEGIN|END|CLAUDE-AGENTS-POINTER|\(\?:BEGIN\|END\))",
    ),
    Allowance(
        2, "5b",
        r"src/cardine/shared/models\.py",
        r'CODEX_PERMISSION_PROFILE = "' + OLD + r'-worktrees"',
    ),
    Allowance(2, "5b", r"tests/test_(?:host_codex_access|host_codex_repair|host_worktree_setup|queue_briefing)\.py",
              r'''(?:permissions\.|["']|\\n)''' + OLD + r'''-worktrees(?=["'.\] =])'''),
    Allowance(
        2, "5b",
        r"(?:src|tests|capabilities)/.*",
        OLD + r"\.rules\b",
    ),
    Allowance(
        2, "5b",
        r"(?:src|scripts|tests|docs)/.*",
        OLD + r"-(?:lean-delivery|governed-sdd)(?:-claude-code)?\b",
    ),
    Allowance(
        2, "5b",
        r"(?:src|scripts|tests|docs)/.*",
        r"(?:commands/|/)?" + OLD + r"-(?:init|task|upgrade|audit)\b",
    ),
    Allowance(
        2, "5b",
        r"src/cardine/hosts/skills\.py",
        OLD + r"-\*",
    ),
    Allowance(
        2, "5b",
        r"(?:src/cardine/hosts/codex|tests/test_host_codex_(?:access|repair)|tests/test_queue_briefing)\.py",
        r"Workspace access plus " + OLD.capitalize() + r"-managed task worktrees\.",
    ),
    Allowance(
        2, "5b",
        r"(?:src/cardine/templates/markers|tests/test_cardine_cli_entry)\.py",
        r"Every " + OLD.capitalize() + r" capability marker",
    ),
    Allowance(
        2, "5b",
        r"(?:src/cardine/hosts/claude|tests/test_host_worktree_setup)\.py",
        r"(?:\"" + OLD + r"\"|" + OLD + r"@local)",
    ),
    Allowance(
        2, "5b",
        r"(?:src/cardine/release/update|scripts/(?:release|upgrade_project)|tests/test_(?:release_self_check|self_update))\.(?:py|sh)",
        r"(?:biagiolibe/|extraKnownMarketplaces\.|cache/|marketplace update |get\(\"|\{\")" + OLD + r"\b",
    ),
    Allowance(
        2, "5b",
        r"(?:scripts/(?:check_repository|align_queue)|src/cardine/(?:hosts/setup|tasks/(?:contract|preflight))|tests/(?:cardine_cli_support|synthetic_upgrade_support|test_(?:codex_rules|codex_worktree_hooks|codex_read_guard|execution_evidence|integration_projections|stop_audit|template_marker_heading|cardine_upgrade_lifecycle)))\.py",
        OLD + r'''(?=\s+(?:worktree|execution|locations|audit|upgrade|adopt|review|codex|task|hook|Reviewer-Integrator)|["'][,\n\)])''',
    ),
    Allowance(
        2, "5b",
        r"tests/test_check_repository\.py",
        r'"name": "' + OLD + r'"',
    ),
    Allowance(
        2, "5b",
        r"tests/program_word_support\.py",
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
        4, "kept: historical records",
        r"(?:tasks/(?:done|handoffs)/.*|tasks/(?:QUEUE[^/]*|TASK_BLUEPRINT|051-rename-strings-and-guard)\.md|PROJECT_PLAN\.md|CHANGELOG\.md|changelog\.d/.*|releases/.*|\.github/.*|README\.md|CONTRIBUTING\.md|WORKFLOW_GUIDE\.md|SECURITY\.md|CODE_OF_CONDUCT\.md|migrations/README\.md|tests/fixtures/release-[^/]+/.*)",
    ),
    Allowance(
        4, "kept: historical design and guides; guides replaced by 11",
        r"docs/(?:ADR_[^/]+\.md|AGENT_OPERATIONS\.md|CLEAN_INSTALL_VERIFICATION\.md|CONSUMER_PROFILES\.md|CONSUMER_ROUTER_ADOPTION_PLAYBOOK\.md|DISTRIBUTION_AND_UPDATE_DESIGN\.md|GOVERNED_WORKFLOW\.md|HOST_CAPABILITY_CONTRACT\.md|HOW_TO_UPGRADE\.md|" + OLD.upper() + r"_SELF_HOSTING_PROFILE\.md|MODULE_SPLIT_PLAN\.md|PLATFORM_SUPPORT\.md|PROJECT_DECLARATION\.md|QUICKSTART\.md|RENAME_PLAN\.md|SINGLE_WORKFLOW_PLAN\.md|TASK_IDENTITY_POLICY\.md|assets/.*)",
    ),
    Allowance(
        5, "10",
        r"src/cardine/legacy/" + OLD + r"_installation\.py",
    ),
    Allowance(
        5, "10",
        r"tests/test_legacy_" + OLD + r"_installation\.py",
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
        inspect(name, 0, "<path>")
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            inspect(name, number, line, lines[number - 2] if number > 1 else "")
    for index, entry in enumerate(allowlist):
        if not used[index]:
            failures.append(f"unused allowlist entry {index}: group {entry.group}, {entry.removal}, {entry.paths}")
    return failures, used


class IdentifierGuardTest(unittest.TestCase):
    def test_repository_has_no_unallowed_identifiers_or_stale_allowances(self):
        failures, _ = scan_repository(ROOT)
        self.assertEqual(failures, [], "\n".join(failures))

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
            marker_allowance = Allowance(2, "5b", r"src/.*", OLD.upper() + r":BEGIN")
            for text in (OLD.capitalize(), OLD.upper(), OLD.upper() + ":BEGIN " + OLD):
                tracked.write_text(text + "\n")
                failures, _ = scan_repository(root, (marker_allowance,))
                self.assertTrue(any(str(tracked.relative_to(root)) + ":1:" in f for f in failures))
            tracked.write_text("Cardine\n")
            untracked = root / (OLD + ".txt")
            untracked.write_text(OLD)
            failures, _ = scan_repository(root, ())
            self.assertTrue(any(untracked.name + ":0:" in f for f in failures))
            self.assertTrue(any(untracked.name + ":1:" in f for f in failures))
            (root / ".gitignore").write_text("*.txt\n")
            self.assertEqual(scan_repository(root, ())[0], [])
            failures, _ = scan_repository(root, (Allowance(2, "5b", "missing/.*"),))
            self.assertTrue(any("unused allowlist entry" in f for f in failures))


if __name__ == "__main__":
    unittest.main()
