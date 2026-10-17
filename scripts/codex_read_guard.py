"""Advisory-safe Codex Bash read guard (task 041).

Only deliberately narrow, static shell forms are recognised.  A parsing or
filesystem error is always an allow: this hook protects context budget, not
command safety.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import meridian


DEFAULT_THRESHOLD = 400
RANGE = re.compile(r"^(\d+)(?:,(\d+))?p$")


@dataclass(frozen=True)
class ReadTarget:
    path: str
    first: int | None = None
    last: int | None = None


def split_commands(command: str) -> list[list[str]]:
    """Split only the chain separators this adapter documents."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    tokens = list(lexer)
    parts: list[list[str]] = [[]]
    for token in tokens:
        if token in {";", "|", "&&"}:
            parts.append([])
        elif token in {"&", "||"}:
            # An unrecognised operator makes the adjacent command unknown.
            parts.append(["__unknown__"])
        else:
            parts[-1].append(token)
    return parts


def sed_target(tokens: list[str]) -> list[ReadTarget]:
    if len(tokens) != 4 or tokens[:2] != ["sed", "-n"]:
        return []
    match = sed_range(tokens)
    if not match or any(char in tokens[3] for char in "$`*?"):
        return []
    return [ReadTarget(tokens[3], int(match.group(1)), int(match.group(2) or match.group(1)))]


def sed_range(tokens: list[str]) -> re.Match[str] | None:
    if len(tokens) not in {3, 4} or tokens[:2] != ["sed", "-n"]:
        return None
    return RANGE.fullmatch(tokens[2])


def simple_targets(tokens: list[str]) -> list[ReadTarget]:
    if not tokens or any(any(char in token for char in "$`*?") for token in tokens):
        return []
    command = tokens[0]
    if command == "cat" and len(tokens) > 1 and all(not token.startswith("-") for token in tokens[1:]):
        return [ReadTarget(token) for token in tokens[1:]]
    if command in {"head", "tail"}:
        count: int | None = None
        rest = tokens[1:]
        if len(rest) >= 2 and rest[0] == "-n" and rest[1].isdigit():
            count, rest = int(rest[1]), rest[2:]
        elif len(rest) >= 1 and re.fullmatch(r"-\d+", rest[0]):
            count, rest = int(rest[0][1:]), rest[1:]
        if count is not None and len(rest) == 1:
            return [ReadTarget(rest[0], 1 if command == "head" else None, count)]
    return []


def extract_targets(command: str) -> list[ReadTarget]:
    """Extract recognised read targets, ignoring every unknown shell form."""
    try:
        parts = split_commands(command)
    except (ValueError, TypeError):
        return []
    targets: list[ReadTarget] = []
    for index, part in enumerate(parts):
        found = sed_target(part) or simple_targets(part)
        if found:
            targets.extend(found)
        # nl file | sed -n range: the pipe creates two parts.
        if part and part[0] == "nl" and len(part) == 2 and index + 1 < len(parts):
            ranged = sed_range(parts[index + 1])
            if ranged:
                targets.append(ReadTarget(part[1], int(ranged.group(1)), int(ranged.group(2) or ranged.group(1))))
    return targets


def threshold_for(project: Path) -> int:
    try:
        profile = project / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
        match = re.search(r"`Read-guard threshold`:\s*(\d+)", profile.read_text(encoding="utf-8"))
        return int(match.group(1)) if match else DEFAULT_THRESHOLD
    except (OSError, ValueError):
        return DEFAULT_THRESHOLD


def is_exempt(path: Path, project: Path) -> bool:
    try:
        relative = path.relative_to(project).as_posix()
    except ValueError:
        return False
    if relative == "LANGUAGE_POLICY.md":
        return True
    try:
        active = meridian.active_worktree_task(project)
        if active and str(path) in active["exempt_paths"]:
            return True
        if active:
            authority = meridian.context_authority(project, str(active["task_id"]), labels_only=True)
            sources = re.findall(r"^### (.+?) —", authority, re.MULTILINE)
            if relative in sources:
                return True
    except meridian.MeridianError:
        pass
    except OSError:
        pass
    try:
        if Path(relative) in meridian.context_router_files(project):
            return True
    except meridian.MeridianError:
        pass
    return False


def router_ceiling_reason(path: Path, project: Path) -> str | None:
    """Return a specific denial for a declared router file above its ceiling."""
    try:
        relative = path.relative_to(project)
        if relative not in meridian.context_router_files(project):
            return None
        _bytes, ceiling = meridian._context_configuration(project)
        with path.open(encoding="utf-8", errors="replace") as source:
            lines = sum(1 for _ in source)
        if lines > ceiling:
            return f"Blocked: router file {relative.as_posix()} ({lines} lines) exceeds its declared ceiling ({ceiling} lines). Shrink the file; do not read it in ranges."
    except (OSError, ValueError, meridian.MeridianError):
        return None
    return None


def display_path(path: Path, project: Path) -> str:
    """Prefer a project-relative denial path without rejecting external files."""
    try:
        return path.relative_to(project).as_posix()
    except ValueError:
        return str(path)


def decision(payload: object) -> tuple[bool, str | None]:
    """Return (allowed, reason); malformed and irrelevant payloads allow."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return True, None
    tool_input = payload.get("tool_input")
    cwd = payload.get("cwd")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str) or not isinstance(cwd, str):
        return True, None
    project = Path(cwd).resolve()
    if not (project / "PROJECT_WORKFLOW.md").is_file():
        return True, None
    budget = threshold_for(project)
    total = 0
    files: list[str] = []
    try:
        for target in extract_targets(tool_input["command"]):
            path = (project / target.path).resolve() if not Path(target.path).is_absolute() else Path(target.path).resolve()
            if not path.is_file():
                continue
            ceiling_reason = router_ceiling_reason(path, project)
            if ceiling_reason:
                return False, ceiling_reason
            if is_exempt(path, project):
                continue
            with path.open(encoding="utf-8", errors="replace") as source:
                lines = sum(1 for _ in source)
            if lines <= budget:
                continue
            if target.first is None and target.last is None:
                effective = lines
            elif target.first is None:
                effective = min(lines, target.last or lines)
            else:
                effective = max(0, min(lines, target.last) - min(lines + 1, target.first) + 1)
            total += effective
            files.append(f"{display_path(path, project)} ({effective} lines)")
    except (OSError, ValueError):
        return True, None
    if total <= budget:
        return True, None
    joined = ", ".join(files)
    return False, (
        f"Blocked: shell read of {joined} returns {total} effective lines, exceeding the read-guard threshold "
        f"({budget} lines). Use `rg -n` to locate lines, then a ranged `sed -n`; for the ADR log or a spec file use "
        "`meridian context authority <TASK-ID>` or `meridian adr show <ADR-ID>`. To override, declare the file "
        "in the task's Authority or raise `Read-guard threshold` in docs/EXECUTION_EVIDENCE_PROFILE.md."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        allowed, reason = decision(payload)
    except Exception:
        return 0
    if allowed:
        return 0
    print(reason, file=sys.stderr)
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": reason}}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
