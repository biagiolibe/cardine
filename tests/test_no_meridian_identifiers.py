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
HISTORIC_PROFILE = "meridian-worktrees"


@dataclass(frozen=True)
class Allowance:
    group: int
    removal: str
    paths: str
    pattern: str | None = None


# One table: path exemptions cover only declared surfaces; content exemptions
# cover the matched identifier, never an unrelated occurrence on the same line.
# OLD is composed to keep the retired name out of the guard definitions.
ALLOWLIST = (
    Allowance(2, "9", r"(?:skills|commands|\.claude-plugin)/.*"),
    Allowance(2, "9", r"src/.*",
              OLD.upper() + r":(?:BEGIN|END|\(\?:BEGIN\|END\))(?:\s+|\\s\+)(?:worktree-permissions|codex-user-rules)\b"),
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
    Allowance(
        2, "9",
        r"src/.*",
        OLD + r"-(?:lean-delivery|governed-sdd)(?:-claude-code)?\b",
    ),
    Allowance(
        2, "9",
        r"src/cardine/hosts/skills\.py",
        OLD + r"-\*",
    ),
    Allowance(
        2, "9",
        r"src/cardine/hosts/claude\.py",
        r"(?:\"" + OLD + r"\"|" + OLD + r"@local)",
    ),
    Allowance(
        5, "10",
        r"src/cardine/legacy/(?:" + OLD + r"_installation|" + OLD + r"_locations|snapshot|conversion_reader)\.py",
    ),
    Allowance(
        5, "kept: the conversion package, while adopt exists (DD2)",
        r"src/cardine/adopt/.*\.py",
    ),
)


def scan_repository(root: Path, allowlist=ALLOWLIST) -> tuple[list[str], Counter]:
    """Return forbidden identifiers and usage counts, including stale allowances."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=root, check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    used = Counter()
    failures = []
    compiled = [(re.compile(entry.paths), re.compile(entry.pattern) if entry.pattern else None)
                for entry in allowlist]

    def inspect(path: str, line_number: int, line: str) -> None:
        for occurrence in re.finditer(OLD, path if line_number == 0 else line, re.IGNORECASE):
            allowed = False
            for index, entry in enumerate(allowlist):
                paths, pattern = compiled[index]
                if not paths.fullmatch(path):
                    continue
                if pattern is None:
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
        if not re.fullmatch(r"(?:src|bin|capabilities|schemas|skills|commands|\.claude-plugin)/.*|pyproject\.toml", name):
            continue
        path = root / name
        if not path.is_file():
            continue
        inspect(name, 0, "<path>")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            inspect(name, number, line)
    for index, entry in enumerate(allowlist):
        if not used[index]:
            failures.append(f"unused allowlist entry {index}: group {entry.group}, {entry.removal}, {entry.paths}")
    return failures, used


class IdentifierGuardTest(unittest.TestCase):
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
            subprocess.run(["git", "add", "."], cwd=root, check=True)
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
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            failures, _ = scan_repository(root, (allowance,))
            self.assertTrue(any("models.py:1:" in failure for failure in failures))

    def test_scope_and_stale_allowances(self):
        with tempfile.TemporaryDirectory(prefix="cardine-identifier-guard-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name in ("src/example.py", "docs/example.md", "tasks/example.md", "tests/example.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(OLD + "\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            failures, _ = scan_repository(root, ())
            self.assertEqual(failures, [f"src/example.py:1: {OLD}"])
            shipped = root / "src/example.py"
            marker = Allowance(2, "9", r"src/.*", OLD.upper() + r":BEGIN")
            for content in (OLD.capitalize(), OLD.upper(), OLD.upper() + ":BEGIN " + OLD):
                shipped.write_text(content + "\n")
                self.assertTrue(any("src/example.py:1:" in failure
                                    for failure in scan_repository(root, (marker,))[0]))
            shipped.write_text("Cardine\n")
            self.assertEqual(scan_repository(root, ())[0], [])
            failures, _ = scan_repository(root, (Allowance(2, "9", r"src/missing.py"),))
            self.assertTrue(any("unused allowlist entry" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
