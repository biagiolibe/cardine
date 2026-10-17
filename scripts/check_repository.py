#!/usr/bin/env python3
"""Small dependency-free checks for Meridian's distributable repository."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402
import release  # noqa: E402

# Deliberately not directly inside migrations/: `meridian.py`'s
# capability_requirements() and migration_ids() glob `migrations/*.json`
# expecting every match to be a migration record (with "id"/"from"/"to"/...
# fields); a baseline file there would satisfy the glob and blow up the first
# reader with a KeyError. A subdirectory is invisible to that non-recursive
# glob, so this file sits one level down instead.
MARKER_BASELINE_PATH = ROOT / "migrations" / "marker-baselines" / "CAPABILITY_MARKER_BASELINES.json"
REQUIRED_FILES = (
    "README.md",
    "VERSION",
    "LICENSE",
    "CONTRIBUTING.md",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "hooks/hooks.json",
    "hooks/queue-briefing.sh",
    "hooks/stop-audit.sh",
    "bin/meridian",
    "scripts/meridian.py",
    "capabilities/catalog-v1.json",
    "capabilities/stop-codes-v1.json",
    "capabilities/retired-text-v1.json",
    "schemas/retired-text-v1.schema.json",
    "schemas/capability-catalog-v1.schema.json",
    "schemas/stop-codes-v1.schema.json",
    "schemas/manifest-v2.schema.json",
    ".meridian/probes/meridian-self-hosting/host-neutral-ci-v1.json",
    ".meridian/probes/meridian-self-hosting/claude-project-v1.json",
    ".meridian/probes/meridian-self-hosting/codex-project-v1.json",
    "migrations/001-review-remediation-record.json",
    "migrations/002-lifecycle-orchestration.json",
    "migrations/003-framework-updater.json",
    "migrations/004-validation-scoping.json",
    "migrations/005-ci-verified-validation.json",
    "migrations/006-capability-markers.json",
    "migrations/007-validation-capability-markers.json",
    "migrations/008-review-remediation-record-v2.json",
    "migrations/009-lifecycle-orchestration-v2.json",
    "migrations/010-project-workflow-baseline-capabilities.json",
    "migrations/011-whole-file-baseline-capabilities.json",
    "migrations/012-agents-claude-residual-capabilities.json",
    "migrations/013-language-policy-v2.json",
    "migrations/048-manifest-capability-profile-schema.json",
    "migrations/052-install-meridian-self-hosting-surfaces.json",
    "migrations/README.md",
    "migrations/ASSISTED_ADOPTION.md",
    "release-baselines/1.0.0/templates/workflows/governed-sdd/PROJECT_WORKFLOW.md",
    "commands/meridian-upgrade.md",
    "commands/meridian-adopt.md",
    "commands/meridian-audit.md",
    "templates/workflows/lean-delivery/PROJECT_WORKFLOW.md",
    "templates/workflows/lean-delivery/AGENTS.md",
    "templates/workflows/lean-delivery/CLAUDE.md",
    "templates/workflows/lean-delivery/LANGUAGE_POLICY.md",
    "templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md",
    "templates/workflows/lean-delivery/docs/EXECUTION_EVIDENCE_PROFILE.md",
    "templates/workflows/lean-delivery/.codex/hooks.json",
    "skills/meridian-lean-delivery/SKILL.md",
    "skills/meridian-lean-delivery-claude-code/SKILL.md",
)
LANGUAGE_POLICY_FILES = (
    "templates/base/LANGUAGE_POLICY.md",
    "templates/workflows/lean-delivery/LANGUAGE_POLICY.md",
    "templates/workflows/governed-sdd/LANGUAGE_POLICY.md",
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
RETIRED_GOVERNED_REVIEW_PHRASES = (
    "uses that same primary checkout",
    "git switch <task-branch>",
    "leave the primary checkout clean and on the task branch",
)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def check_required_files() -> None:
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            fail(f"required file is missing: {name}")


def check_changelog_fragments(root: Path = ROOT) -> None:
    directory = root / "changelog.d"
    if not directory.is_dir():
        fail("changelog.d is missing")
    if not (directory / "README.md").is_file():
        fail("changelog.d/README.md is missing")
    try:
        release.render_fragments(root)
    except release.FragmentError as error:
        fail(str(error))


def check_template_context_sizes() -> None:
    """Keep the shipped role startup sets below their documented ceilings."""
    labels = {"lean-delivery": "Lean Delivery", "governed-sdd": "Governed SDD"}
    for mode, workflow_label in labels.items():
        project = ROOT / "templates" / "workflows" / mode
        policy = project / meridian.CONTEXT_SIZE_POLICY_PATH
        if not policy.is_file():
            fail(f"context-size policy is missing: {policy.relative_to(ROOT)}")
        rows = {
            role: int(ceiling)
            for found_workflow, role, ceiling in re.findall(
                r"^\| ([^|]+) \| ([a-z]+) \| ([0-9]+) \|$", policy.read_text(encoding="utf-8"), re.MULTILINE
            )
            if found_workflow == workflow_label
        }
        for role in meridian.CONTEXT_SIZE_ROLES[mode]:
            if role not in rows:
                fail(f"context-size ceiling is missing for {mode}/{role}")
            report = meridian.context_size_report(project, role)
            actual = int(report["total"]["bytes"])
            if actual > rows[role]:
                fail(f"context-size ceiling exceeded for {mode}/{role}: {actual} bytes > {rows[role]} bytes")


def check_language_policy() -> None:
    for name in LANGUAGE_POLICY_FILES:
        path = ROOT / name
        if not path.is_file():
            fail(f"language policy template is missing: {name}")
        text = path.read_text(encoding="utf-8")
        for required_text in (
            "[Conversation language]",
            "another language is not a request to switch languages",
            "All text that remains in the repository must be written in English.",
        ):
            if required_text not in text:
                fail(f"language policy is incomplete: {name}")

    for name in (
        "templates/base/CLAUDE.md",
        "templates/workflows/lean-delivery/AGENTS.md",
        "templates/workflows/lean-delivery/CLAUDE.md",
        "templates/workflows/governed-sdd/AGENTS.md",
        "templates/workflows/governed-sdd/CLAUDE.md",
    ):
        if "LANGUAGE_POLICY.md" not in (ROOT / name).read_text(encoding="utf-8"):
            fail(f"agent instructions do not load the language policy: {name}")

    mode_lock_files = (
        "commands/meridian-task.md",
        "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md",
        "templates/workflows/governed-sdd/AGENTS.md",
        "templates/workflows/governed-sdd/CLAUDE.md",
        "templates/workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md",
        "templates/workflows/governed-sdd/docs/OPERATOR_PROMPTS.md",
    )
    for name in mode_lock_files:
        text = (ROOT / name).read_text(encoding="utf-8")
        if "GOVERNED_SDD" not in text or "BLOCKED" not in text:
            fail(f"governed-SDD mode lock is incomplete: {name}")

    lean_mode_lock_files = (
        "templates/workflows/lean-delivery/PROJECT_WORKFLOW.md",
        "templates/workflows/lean-delivery/AGENTS.md",
        "templates/workflows/lean-delivery/CLAUDE.md",
        "skills/meridian-lean-delivery/SKILL.md",
        "skills/meridian-lean-delivery-claude-code/SKILL.md",
    )
    for name in lean_mode_lock_files:
        text = (ROOT / name).read_text(encoding="utf-8")
        if "LEAN_DELIVERY" not in text or "BLOCKED" not in text:
            fail(f"Lean Delivery mode lock is incomplete: {name}")

    operator_prompts = ROOT / "templates/workflows/governed-sdd/docs/OPERATOR_PROMPTS.md"
    if not operator_prompts.is_file():
        fail("governed-SDD operator prompts are missing")
    if "This non-normative cookbook" not in operator_prompts.read_text(
        encoding="utf-8"
    ):
        fail("governed-SDD operator prompts must remain non-normative")


def check_governed_review_worktree_contract(root: Path = ROOT) -> None:
    workflow = root / "templates" / "workflows" / "governed-sdd"
    review_paths = (
        workflow / "PROJECT_WORKFLOW.md",
        workflow / "docs" / "CODE_REVIEW_PROMPT.md",
        workflow / "docs" / "LIFECYCLE_ORCHESTRATION.md",
        workflow / "docs" / "workflows" / "REVIEW.md",
    )
    for path in review_paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for phrase in RETIRED_GOVERNED_REVIEW_PHRASES:
            if phrase in lowered:
                fail(
                    f"retired primary-checkout review instruction in "
                    f"{path.relative_to(root)}: {phrase}"
                )

    review = review_paths[-1].read_text(encoding="utf-8")
    preflight_match = re.search(r"<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v\d+ -->", review)
    boundary_match = re.search(r"<!-- MERIDIAN:BEGIN capability=review-mode-boundary v\d+ -->", review)
    if preflight_match is None or boundary_match is None:
        fail("governed review must begin with the task-worktree preflight")
    preflight, boundary = preflight_match.group(0), boundary_match.group(0)
    required = (
        "Before reading the assigned task",
        "meridian worktree check <TASK-ID>",
        "stops before any other read",
        "git worktree list\n   --porcelain",
        "git -C\n   <absolute-task-worktree>",
        "empty `git status --short`",
        "task and base commits exist",
        "Only after every preflight check passes",
        "initial current directory is never treated as\nthe task checkout",
    )
    if preflight not in review or boundary not in review or review.index(preflight) > review.index(boundary):
        fail("governed review must begin with the task-worktree preflight")
    for fragment in required:
        if fragment not in review:
            fail(f"governed task-worktree review preflight is incomplete: {fragment}")


MANAGED_BLOCK = re.compile(
    r"<!-- MERIDIAN:BEGIN capability=(?P<capability>[\w-]+) v(?P<version>\d+) -->(?P<body>.*?)<!-- MERIDIAN:END -->",
    re.DOTALL,
)
FORBIDDEN_TEMPLATE_TEXT = (
    "task-<TASK-ID>",
    "<PROJECT_NAME>",
    "<project-slug>",
    "meridian Reviewer-Integrator",
    "Project integration smoke command",
)
# A managed block may state what the queue is or who applies its status, but never
# that a task branch, reviewer, or owner edits a queue row.
QUEUE_EDIT_STATEMENT = re.compile(
    r"queue (?:row|status|record)s?\b|task(?:/| and )queue|queue and task", re.IGNORECASE
)
# Governed blocks name a queue, queue-archive, review, or handoff location by role
# and defer to `meridian locations`; only execution-assets may state the defaults.
LITERAL_LOCATION = re.compile(r"tasks/QUEUE\.md|QUEUE_ARCHIVE\.md|TASK_QUEUE\.md|tasks/reviews/|tasks/handoffs/")
LITERAL_LOCATION_EXEMPT_CAPABILITIES = ("execution-assets",)
REVIEWER_IDENTITY_CAPABILITY = "reviewer-integrator-identity"


def check_governed_lifecycle_text(root: Path = ROOT) -> None:
    """Keep managed lifecycle text free of queue edits, literal locations, and placeholders.

    The literal-location rule is Governed-only: Lean's `git-workflow` block keeps
    naming the governance files its task branches must not edit, because task 145
    scopes Lean to the branch-name and push rules.
    """
    workflows = root / "templates" / "workflows"
    for path in sorted(workflows.rglob("*.md")):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        for phrase in FORBIDDEN_TEMPLATE_TEXT:
            if phrase in text:
                fail(f"{relative} contains retired or placeholder text: {phrase}")
        governed = "governed-sdd" in path.parts
        for block in MANAGED_BLOCK.finditer(text):
            capability, body = block.group("capability"), block.group("body")
            edit = QUEUE_EDIT_STATEMENT.search(body)
            if edit:
                fail(f"{relative}: capability {capability} says a role edits a queue row: {edit.group(0)!r}")
            if governed and capability not in LITERAL_LOCATION_EXEMPT_CAPABILITIES:
                literal = LITERAL_LOCATION.search(body)
                if literal:
                    fail(f"{relative}: capability {capability} names a literal location: {literal.group(0)!r}")
    governed_root = workflows / "governed-sdd"
    identity_blocks = []
    for path in sorted(governed_root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"--author=", text):
            enclosing = next(
                (block for block in MANAGED_BLOCK.finditer(text) if block.start() <= match.start() < block.end()),
                None,
            )
            identity_blocks.append((path.relative_to(root), enclosing.group("capability") if enclosing else None))
    if len(identity_blocks) != 1 or identity_blocks[0][1] != REVIEWER_IDENTITY_CAPABILITY:
        fail(
            "the reviewer identity rule must appear in exactly one managed block "
            f"({REVIEWER_IDENTITY_CAPABILITY}): {identity_blocks}"
        )
    repository_workflow = root / "PROJECT_WORKFLOW.md"
    if repository_workflow.is_file() and "Project integration smoke command" in repository_workflow.read_text(encoding="utf-8"):
        fail("PROJECT_WORKFLOW.md contains retired text: Project integration smoke command")


STOP_TOKEN = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"
STOP_AFTER_BLOCKED = re.compile(rf"\bBLOCKED\s+`?({STOP_TOKEN})\b")
# A stop-code list: two or more quoted tokens joined by commas, "or", "and", or
# "through". It counts only when it holds a registered code, so lists of other
# uppercase words (for example the integration decisions) are not stop codes.
_QUOTED_TOKEN = rf"([`\"])({STOP_TOKEN})\1"
STOP_CODE_LIST = re.compile(
    rf"{_QUOTED_TOKEN}(?:(?:,\s*|\s+)(?:(?:or|and|through)\s+)?{_QUOTED_TOKEN})+"
)
STOP_LIST_TEST_FILES = ("tests/test_project_console.py",)


def managed_stop_text_files(root: Path) -> list[Path]:
    """Return the managed templates and this repository's own managed copies."""
    paths = set((root / "templates").rglob("*.md"))
    manifest = root / ".meridian" / "manifest.json"
    if manifest.is_file():
        managed = json.loads(manifest.read_text(encoding="utf-8")).get("managedFiles", {})
        paths.update(root / name for name in managed if name.endswith(".md") and (root / name).is_file())
    return sorted(paths)


def stop_tokens_in(text: str, known: set[str]) -> list[tuple[int, str]]:
    """Return (offset, token) for each stop token used as a stop in `text`."""
    found = [(match.start(1), match.group(1)) for match in STOP_AFTER_BLOCKED.finditer(text)]
    for run in STOP_CODE_LIST.finditer(text):
        tokens = [(run.start() + token.start(2), token.group(2)) for token in re.finditer(_QUOTED_TOKEN, run.group(0))]
        if any(token in known for _offset, token in tokens):
            found.extend(tokens)
    return found


BLOCKED_WORD = re.compile(r"\bBLOCKED\b")
_BLOCKED_TOKEN_AFTER = re.compile(rf"[ \t]*`?[ \t]*(<CODE>|{STOP_TOKEN})")
_VERDICT = r"(?:APPROVE|CHANGES_REQUESTED)"
_VERDICT_SEPARATOR = r"[`>\s]*(?:\||,\s*or\b|,|\bor\b)[`\s]*"
# A review or adoption verdict enumeration, such as `APPROVE | CHANGES_REQUESTED | BLOCKED`,
# names a verdict value and is not a stop.
VERDICT_ENUMERATION = re.compile(
    rf"{_VERDICT}{_VERDICT_SEPARATOR}(?:{_VERDICT}{_VERDICT_SEPARATOR})*BLOCKED"
    rf"|BLOCKED{_VERDICT_SEPARATOR}{_VERDICT}"
)
# The only f-string through which the CLI prints a stop; its code is a registered value.
CLI_STOP_FORMAT = "BLOCKED {}: {}; resume: {}"


def uncoded_blocked_offsets(text: str, known: set[str]) -> list[int]:
    """Return the offsets of each `BLOCKED` in `text` that is not followed by a stop code.

    A registered code or the `<CODE>` placeholder follows a coded stop. A verdict
    enumeration is not a stop.
    """
    exempt = [match.span() for match in VERDICT_ENUMERATION.finditer(text)]
    offsets = []
    for match in BLOCKED_WORD.finditer(text):
        coded = _BLOCKED_TOKEN_AFTER.match(text, match.end())
        if coded and (coded.group(1) == "<CODE>" or coded.group(1) in known):
            continue
        if any(start <= match.start() < end for start, end in exempt):
            continue
        offsets.append(match.start())
    return offsets


def cli_string_literals(source: str) -> list[tuple[int, str]]:
    """Return (line, text) for each string the CLI source holds, with f-string fields as `{}`."""
    tree = ast.parse(source)
    inside_fstring = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "{}"
                for part in node.values
            )
            found.append((node.lineno, text))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside_fstring:
            found.append((node.lineno, node.value))
    return found


def check_uncoded_blocked(root: Path, known: set[str], texts: dict[Path, str]) -> None:
    """Fail on a `BLOCKED` in managed text or in the CLI that carries no registered stop code."""
    for path, text in texts.items():
        for offset in uncoded_blocked_offsets(text, known):
            line = text.count("\n", 0, offset) + 1
            fail(f"{path.relative_to(root)}:{line}: BLOCKED without a registered stop code")
    cli = root / "scripts" / "meridian.py"
    if not cli.is_file():
        return
    for line, text in cli_string_literals(cli.read_text(encoding="utf-8")):
        if text == "BLOCKED" or text == CLI_STOP_FORMAT:
            continue  # a verdict or state value, and the helper's single output format
        if uncoded_blocked_offsets(text, known):
            fail(f"scripts/meridian.py:{line}: BLOCKED without a registered stop code")


def check_stop_code_registry(root: Path = ROOT) -> None:
    """Keep managed text, the CLI, and tests in agreement with the stop-code registry."""
    registry = json.loads((root / "capabilities" / "stop-codes-v1.json").read_text(encoding="utf-8"))
    entries = {entry["code"]: entry for entry in registry["stops"]}
    texts = {path: path.read_text(encoding="utf-8") for path in managed_stop_text_files(root)}
    scanned = dict(texts)
    for name in STOP_LIST_TEST_FILES:
        if (root / name).is_file():
            scanned[root / name] = (root / name).read_text(encoding="utf-8")
    for path, text in scanned.items():
        for offset, token in stop_tokens_in(text, set(entries)):
            if token not in entries:
                line = text.count("\n", 0, offset) + 1
                fail(f"{path.relative_to(root)}:{line}: unregistered stop code {token}")
    check_uncoded_blocked(root, set(entries), texts)
    test_names = set()
    for source in (root / "tests").glob("test_*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                test_names.update(
                    f"tests.{source.stem}.{node.name}.{item.name}"
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
    for code, entry in entries.items():
        if entry["class"] != "tool":
            continue
        if not entry.get("test"):
            fail(f"stop code {code} is class tool but has no test field")
        if entry["test"] not in test_names:
            fail(f"stop code {code} names a test that does not exist: {entry['test']}")
    cli = root / "scripts" / "meridian.py"
    emitted = cli.read_text(encoding="utf-8") if cli.is_file() else ""
    for code in entries:
        mention = re.compile(rf"\b{code}\b")
        if not any(mention.search(text) for text in texts.values()) and not mention.search(emitted):
            fail(f"stop code {code} is registered but no managed text or CLI output mentions it")


def check_json() -> None:
    for path in ROOT.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            fail(f"invalid JSON in {path.relative_to(ROOT)}: {error}")


def check_plugin_version(root: Path = ROOT) -> None:
    expected_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    plugin_manifest = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    plugin_version = plugin_manifest.get("version")
    if plugin_version != expected_version:
        fail(
            ".claude-plugin/plugin.json version "
            f"{plugin_version!r} does not match VERSION {expected_version!r}"
        )


def check_capability_catalog(root: Path = ROOT) -> None:
    try:
        catalog = meridian.load_capability_catalog(root)
    except meridian.MeridianError as error:
        fail(f"invalid capability catalog: {error}")
    profile = catalog.profile("meridian-self-hosting")
    if profile is None or not profile.capabilities:
        fail("capability catalog is missing the versioned meridian-self-hosting profile")
    transition_path = root / "migrations/048-manifest-capability-profile-schema.json"
    if not transition_path.is_file():
        fail("manifest capability-profile schema transition is missing")
    transition = json.loads(transition_path.read_text(encoding="utf-8")).get(
        "schemaTransition", {}
    )
    if transition != {
        "catalogVersion": meridian.CAPABILITY_CATALOG_VERSION,
        "fromProtocolVersion": meridian.LEGACY_PROTOCOL_VERSION,
        "legacyWorkflowModeField": "mode",
        "toProtocolVersion": meridian.PROTOCOL_VERSION,
        "workflowModeField": "workflowMode",
    }:
        fail("manifest capability-profile schema transition does not match the parser")


def check_migrations(root: Path = ROOT) -> None:
    migration_paths = sorted((root / "migrations").glob("[0-9][0-9][0-9]-*.json"))
    if not migration_paths:
        fail("no framework migrations are defined")
    tag_listing = subprocess.run(
        ["git", "-C", str(root), "tag", "--list", "v*"],
        check=False,
        capture_output=True,
        text=True,
    )
    published_tags = set(tag_listing.stdout.splitlines()) if tag_listing.returncode == 0 else set()
    previous_to = None
    for index, path in enumerate(migration_paths, start=1):
        data = json.loads(path.read_text(encoding="utf-8"))
        expected_prefix = f"{index:03d}-"
        required = ("id", "from", "to", "description", "managedPaths", "verification")
        if not path.name.startswith(expected_prefix) or not str(data.get("id", "")).startswith(expected_prefix):
            fail(f"migration sequence is invalid: {path.relative_to(root)}")
        if any(key not in data for key in required):
            fail(f"migration is incomplete: {path.relative_to(root)}")
        if data["from"] == data["to"]:
            fail(f"migration cannot target the same version: {path.relative_to(root)}")
        for error in meridian.validate_adopt_existing_paths(data):
            fail(f"invalid migration adoption declaration in {path.relative_to(root)}: {error}")
        if previous_to is not None and data["from"] != previous_to:
            fail(f"migration versions are not contiguous: {path.relative_to(root)}")
        target_tag = f"v{data['to']}"
        release_path = root / "releases" / f"{data['to']}.json"
        release_migrations = (
            json.loads(release_path.read_text(encoding="utf-8")).get("migrations", [])
            if release_path.is_file()
            else []
        )
        if target_tag in published_tags and data["id"] not in release_migrations:
            fail(
                f"migration targets an already tagged version without a release-ledger entry: "
                f"{path.relative_to(root)} ({target_tag})"
            )
        previous_to = data["to"]
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    # A CLI-only release bumps VERSION without a migration, so the last
    # migration may lag behind VERSION but must never be ahead of it.
    if meridian.version_key(previous_to) > meridian.version_key(current_version):
        fail("a migration must never target a version ahead of the current release")
    for error in meridian.validate_capability_moves(root, "governed-sdd"):
        fail(f"invalid capability move: {error}")


def catalog_surface_additions(
    previous: dict[str, object], current: dict[str, object]
) -> list[tuple[str, str]]:
    """`(capability, path)` pairs the current catalog adds to a capability the
    previous catalog already declared."""
    previous_capabilities = previous.get("capabilities", {})
    additions = []
    for capability_id, capability in sorted(current.get("capabilities", {}).items()):
        if capability_id not in previous_capabilities:
            continue
        known = {
            surface["path"] for surface in previous_capabilities[capability_id]["managedSurfaces"]
        }
        additions.extend(
            (capability_id, surface["path"])
            for surface in capability["managedSurfaces"]
            if surface["path"] not in known
        )
    return additions


def check_catalog_surface_migrations(
    root: Path = ROOT,
    previous_catalog: dict[str, object] | None = None,
    previous_version: str = "0.0.0",
) -> None:
    """A path added to a capability's managed surface must be listed in `managedPaths`
    of a migration of the next release; otherwise projects that declare the
    surface are not told about it."""
    if previous_catalog is None:
        current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
        listing = subprocess.run(
            ["git", "-C", str(root), "tag", "--list", "v[0-9]*"],
            check=False,
            capture_output=True,
            text=True,
        )
        earlier = sorted(
            (
                tag
                for tag in listing.stdout.split()
                if re.fullmatch(r"v\d+\.\d+\.\d+", tag)
                and meridian.version_key(tag[1:]) < meridian.version_key(current_version)
            ),
            key=lambda tag: meridian.version_key(tag[1:]),
        )
        if not earlier:
            return
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{earlier[-1]}:{meridian.CAPABILITY_CATALOG_PATH}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if shown.returncode != 0:
            return
        previous_catalog = json.loads(shown.stdout)
        previous_version = earlier[-1][1:]
    current_catalog = json.loads((root / meridian.CAPABILITY_CATALOG_PATH).read_text(encoding="utf-8"))
    listed: set[str] = set()
    for path in sorted((root / "migrations").glob("[0-9][0-9][0-9]-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if meridian.version_key(str(data["to"])) > meridian.version_key(previous_version):
            listed.update(str(item) for item in data.get("managedPaths", []))
    for capability_id, surface_path in catalog_surface_additions(previous_catalog, current_catalog):
        if surface_path not in listed:
            fail(
                f"capability {capability_id} adds managed surface {surface_path} but no migration "
                "after the previous release lists it in managedPaths"
            )


RELEASE_FIELDS = (
    "version",
    "releaseDate",
    "gitTag",
    "protocolVersion",
    "workflowBaselineVersion",
    "baselineChanged",
    "migrations",
)


def check_releases(root: Path = ROOT) -> None:
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    release_dir = root / "releases"
    paths = list(release_dir.glob("*.json")) if release_dir.is_dir() else []
    # Numeric order, so 1.1.10 follows 1.1.9; duplicates cannot occur per filename.
    paths.sort(key=lambda path: meridian.version_key(re.split(r"[-+]", path.stem)[0]))
    if not any(path.stem == current_version for path in paths):
        fail(f"releases/{current_version}.json is missing for the current VERSION")
    migration_targets = {}
    for path in (root / "migrations").glob("[0-9][0-9][0-9]-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        migration_targets[str(data.get("id", path.stem))] = str(data["to"])
    records = []
    for path in paths:
        relative = path.relative_to(root)
        data = json.loads(path.read_text(encoding="utf-8"))
        if set(data) != set(RELEASE_FIELDS):
            fail(f"{relative}: fields must be exactly {', '.join(RELEASE_FIELDS)}")
        if data["version"] != path.stem:
            fail(f"{relative}: version {data['version']!r} does not match the filename")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(data["version"])):
            fail(f"{relative}: version must not carry a prerelease or build suffix")
        migrations = data["migrations"]
        if not isinstance(migrations, list):
            fail(f"{relative}: migrations must be a list")
        if data["baselineChanged"] is not bool(migrations):
            fail(f"{relative}: baselineChanged must be true iff migrations is non-empty")
        for migration_id in migrations:
            if migration_targets.get(migration_id) != data["workflowBaselineVersion"]:
                fail(
                    f"{relative}: migration {migration_id!r} does not target "
                    "workflowBaselineVersion"
                )
        records.append(data)
    versions = [meridian.version_key(record["version"]) for record in records]
    if any(a >= b for a, b in zip(versions, versions[1:])):
        fail("release versions are not monotonically increasing across files")
    latest = max(records, key=lambda record: meridian.version_key(record["version"]))
    try:
        expected_baseline = meridian.latest_migration_to(root, latest["version"])
    except meridian.MeridianError as error:
        fail(f"cannot derive workflowBaselineVersion: {error}")
    if latest["workflowBaselineVersion"] != expected_baseline:
        fail(
            f"releases/{latest['version']}.json workflowBaselineVersion does not match "
            f"the migration-derived baseline {expected_baseline}"
        )


def check_bash() -> None:
    for path in ROOT.rglob("*.sh"):
        result = subprocess.run(
            ["bash", "-n", str(path)], check=False, capture_output=True, text=True
        )
        if result.returncode:
            fail(f"invalid Bash in {path.relative_to(ROOT)}: {result.stderr.strip()}")


def check_local_markdown_links() -> None:
    for path in ROOT.rglob("*.md"):
        relative_path = path.relative_to(ROOT)
        # Templates deliberately link to files that an initialized project may
        # create later (for example, QUEUE_ARCHIVE.md). They are examples of a
        # future project tree, not broken links in this repository.
        if "templates" in relative_path.parts or relative_path == Path(
            "tasks/QUEUE_TEMPLATE.md"
        ):
            continue
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            destination = (path.parent / target).resolve()
            if not destination.exists():
                # Task branches archive records before integrate stage owns
                # the corresponding queue-row relink.
                if (
                    relative_path == Path("tasks/QUEUE.md")
                    and destination.parent == (ROOT / "tasks").resolve()
                    and destination.suffix == ".md"
                    and (ROOT / "tasks/done" / destination.name).is_file()
                ):
                    print(
                        f"INFO: pending archive link in {relative_path}: {target}; "
                        "integrate stage relinks it."
                    )
                    continue
                fail(
                    f"broken local Markdown link in {relative_path}: {target}"
                )


def current_marker_baselines(root: Path = ROOT) -> dict[str, dict[str, dict[str, object]]]:
    """capability marker content, by managed template file, for every mode.

    Every managed template (`meridian.managed_files`, the same set a project
    actually receives and `meridian audit` checks) is scanned for its capability
    markers. The result maps relative file path -> capability -> {version,
    sha256 of that marker's exact content}. Two templates can legitimately hold
    different content for the same capability+version (task 014's
    `command-triggers` v1 differs between `AGENTS.md` and `CLAUDE.md` by
    design), so content is keyed per file, never merged across files.
    """
    marked_content = re.compile(
        r"<!-- MERIDIAN:BEGIN capability=([a-z0-9-]+) v(\d+) -->\n?(.*?)<!-- MERIDIAN:END -->",
        re.DOTALL,
    )
    baselines: dict[str, dict[str, dict[str, object]]] = {}
    for mode in meridian.CLAUDE_MD_SHARED_ANCHOR:
        for item in meridian.managed_files(root, mode):
            relative = str(item.source.relative_to(root))
            if relative in baselines:
                continue
            text = item.source.read_text(encoding="utf-8")
            markers: dict[str, dict[str, object]] = {}
            for capability, version, content in marked_content.findall(text):
                markers[capability] = {
                    "version": int(version),
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            if markers:
                baselines[relative] = markers
    return baselines


def write_marker_baselines(root: Path = ROOT) -> None:
    baseline_path = root / "migrations" / "marker-baselines" / "CAPABILITY_MARKER_BASELINES.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(current_marker_baselines(root), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check_capability_marker_baselines(root: Path = ROOT) -> None:
    """Protected marker content may change only via a version bump (task 014).

    `MARKER_BASELINE_PATH` records the content each template's capability
    markers held the last time a developer deliberately ran
    `check_repository.py --write-marker-baselines`, immediately after choosing
    to introduce or bump a marker. Comparing the live templates against that
    record catches both a hand edit and a generator regression: same version,
    different content is always a failure; any other mismatch means the
    baseline itself is stale and must be regenerated as part of the same
    change, so the record stays an explicit, reviewed act, not something a
    tool updates on its own.
    """
    baseline_path = root / "migrations" / "marker-baselines" / "CAPABILITY_MARKER_BASELINES.json"
    if not baseline_path.is_file():
        fail(f"capability marker baseline is missing: {baseline_path.relative_to(root)}")
    recorded = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = current_marker_baselines(root)
    for relative, markers in current.items():
        recorded_file = recorded.get(relative, {})
        for capability, info in markers.items():
            baseline = recorded_file.get(capability)
            if baseline is None:
                fail(
                    f"{relative}: capability={capability} v{info['version']} has no recorded baseline; "
                    "run `python3 scripts/check_repository.py --write-marker-baselines` after a deliberate change"
                )
            elif baseline["version"] == info["version"] and baseline["sha256"] != info["sha256"]:
                fail(
                    f"{relative}: capability={capability} v{info['version']} — protected content changed "
                    "without a version bump; restore the released text or bump the version as a deliberate "
                    "migration"
                )
            elif baseline["version"] != info["version"] or baseline["sha256"] != info["sha256"]:
                fail(
                    f"{relative}: capability={capability} v{info['version']} does not match its recorded "
                    "baseline; run `python3 scripts/check_repository.py --write-marker-baselines` to record "
                    "this deliberate change"
                )
    retired = meridian.retired_capability_ids(root)
    for relative, markers in recorded.items():
        current_file = current.get(relative, {})
        for capability in markers:
            if capability not in current_file and capability not in retired:
                fail(f"{relative}: recorded capability={capability} baseline no longer present in the template")


def managed_digest_diagnostics(root: Path = ROOT) -> list[str]:
    """Return managed-copy and installation-evidence drift without host probes."""
    try:
        manifest = meridian.load_manifest(root, root)
        catalog = meridian.load_capability_catalog(root)
        profiles = meridian.parse_capability_profiles(manifest, catalog)
    except meridian.MeridianError as error:
        return [str(error)]
    managed_files = manifest["managedFiles"]
    assert isinstance(managed_files, dict)
    diagnostics: list[str] = []
    declared_paths: set[str] = set()
    for profile in profiles:
        for declaration in profile.capabilities:
            declared_paths.update(
                surface.path for surface in declaration.managed_surface if surface.form == "managed-copy"
            )
            _identities, failures = meridian.installation_surface_diagnostics(
                root, declaration, managed_files
            )
            diagnostics.extend(
                failure for failure in failures
                if "managed-copy" in failure or failure.startswith("stale digest evidence")
            )
    diagnostics.extend(
        diagnostic
        for _relative, diagnostic in meridian.managed_copy_drift(
            root, managed_files, skip_paths=declared_paths
        )
    )
    return diagnostics


def check_managed_digests(root: Path = ROOT) -> None:
    diagnostics = managed_digest_diagnostics(root)
    if not diagnostics:
        return
    refresh = (
        "run `python3 scripts/check_repository.py --write-managed-digests` "
        "after a deliberate managed-copy edit and review the resulting diff"
    )
    for diagnostic in diagnostics:
        print(f"FAIL: {diagnostic}; {refresh}")
    raise SystemExit(1)


def check_self_hosting_baseline(root: Path = ROOT) -> None:
    """Fail when this repository's installed baseline lags the newest released migration."""
    manifest_path = root / ".meridian" / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = meridian.manifest_baseline_version(manifest)
    expected = meridian.latest_migration_to(root, meridian.read_version(root))
    if meridian.version_key(recorded) < meridian.version_key(expected):
        fail(
            f".meridian/manifest.json workflowBaselineVersion {recorded} is older than the newest "
            f"migration baseline {expected} that VERSION includes; run "
            "`bin/meridian upgrade --project . --check`, then `--apply` (see CONTRIBUTING.md, "
            "\"Managed copies of this repository\")"
        )


def write_managed_digests(root: Path = ROOT) -> list[str]:
    """Refresh managed-file digests and matching profile evidence explicitly."""
    manifest_path = root / ".meridian" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    managed_files = manifest.get("managedFiles")
    if not isinstance(managed_files, dict):
        fail("manifest managedFiles must be an object")
    refreshed: dict[str, tuple[str, str]] = {}
    for relative, recorded in managed_files.items():
        path = root / relative
        if not path.is_file():
            fail(f"refusing to write managed digests: listed file is missing: {relative}")
        current = meridian.sha256(path)
        if recorded != current:
            refreshed[relative] = (str(recorded), current)
    profiles = manifest.get("capabilityProfiles", {})
    # `upgrade --apply` rebuilds managedFiles from the template's managed list, so
    # a managed-copy surface a profile declares beyond that list loses its digest.
    for profile in profiles.values() if isinstance(profiles, dict) else ():
        capabilities = profile.get("capabilities") if isinstance(profile, dict) else None
        for declaration in capabilities.values() if isinstance(capabilities, dict) else ():
            for surface in declaration.get("managedSurface", []) if isinstance(declaration, dict) else ():
                relative = surface.get("path") if isinstance(surface, dict) else None
                if (
                    isinstance(relative, str)
                    and surface.get("form") == "managed-copy"
                    and relative not in managed_files
                    and relative not in refreshed
                ):
                    path = root / relative
                    if not path.is_file():
                        fail(f"refusing to write managed digests: declared file is missing: {relative}")
                    refreshed[relative] = ("absent", meridian.sha256(path))
    for relative, (_recorded, current) in refreshed.items():
        managed_files[relative] = current
    ordered = dict(sorted(managed_files.items()))
    managed_files.clear()
    managed_files.update(ordered)
    evidence_refreshed: list[str] = []
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict) or not isinstance(profile.get("capabilities"), dict):
                continue
            for capability_id, declaration in profile["capabilities"].items():
                if not isinstance(declaration, dict):
                    continue
                surfaces = declaration.get("managedSurface")
                installation = declaration.get("installation")
                if not isinstance(surfaces, list) or not isinstance(installation, dict):
                    continue
                if not any(isinstance(item, dict) and item.get("form") == "managed-copy" for item in surfaces):
                    continue
                # `upgrade --apply` rewrites managedFiles but not this evidence, so it is
                # recomputed from the files, as the install builds it, not mapped from old digests.
                digests = {
                    f"sha256:{meridian.sha256(root / item['path'])}"
                    for item in surfaces
                    if isinstance(item, dict)
                    and item.get("form") != "declaration-only"
                    and (root / str(item.get("path"))).is_file()
                }
                if digests and installation.get("evidence") != sorted(digests):
                    installation["evidence"] = sorted(digests)
                    evidence_refreshed.append(f"{profile_id}/{capability_id}: installation evidence")
    if refreshed or evidence_refreshed:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return [
        *(f"{relative}: {recorded} -> {current}" for relative, (recorded, current) in refreshed.items()),
        *evidence_refreshed,
    ]


# Tracked records identify checkouts and worktrees by names or paths relative
# to a root, so they resolve on every machine. Absolute home-directory paths
# exist only at runtime. Files listed here are frozen exceptions; none today.
MACHINE_PATH_ALLOWED_FILES: frozenset[str] = frozenset()
MACHINE_PATH_PATTERN = re.compile(
    r"/Users/[A-Za-z0-9_.-]+/"
    r"|/home/[A-Za-z0-9_.-]+/"
    r"|[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+[\\/]"
)


def check_no_machine_paths(
    root: Path = ROOT, allowed: frozenset[str] = MACHINE_PATH_ALLOWED_FILES
) -> None:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        fail("cannot list tracked files to check for machine-specific paths")
    for name in listed.stdout.decode("utf-8").split("\0"):
        path = root / name
        if not name or name in allowed or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if MACHINE_PATH_PATTERN.search(line):
                fail(f"machine-specific absolute path in {name}:{number}")


# Private consumer identities are never stored in clear text in this guard.
DENIED_NAME_HASHES = frozenset({
    "0a5cec0b348b57fed596878cf03760d9475f3d2a84e62c61bf139945cea9389f",
    "b62149e19a473376ecf8cc88196d4a465572b126d6112a34461fb09e403637c1",
})


def check_no_private_names(
    root: Path = ROOT, denied_hashes: frozenset[str] = DENIED_NAME_HASHES
) -> None:
    """Check all tracked file contents, including archived task records."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, check=False,
    )
    if listed.returncode != 0:
        fail("cannot list tracked files to check for private names")
    for name in listed.stdout.decode("utf-8").split("\0"):
        path = root / name
        if not name or not path.is_file():
            continue
        # Byte decoding preserves ASCII tokens even in non-text artifacts.
        content = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(content.splitlines(), start=1):
            # Unicode word characters except underscore; punctuation, including
            # underscore, hyphen, dot and slash, delimits each candidate.
            for token in re.findall(r"[^\W_]+", line):
                if hashlib.sha256(token.lower().encode("utf-8")).hexdigest() in denied_hashes:
                    fail(f"private consumer name in {name}:{number}")


def main() -> None:
    if "--write-managed-digests" in sys.argv[1:]:
        changes = write_managed_digests()
        for change in changes:
            print(f"Updated managed digest: {change}")
        if not changes:
            print("Managed digests are already current.")
        return
    if "--write-marker-baselines" in sys.argv[1:]:
        write_marker_baselines()
        print(f"Wrote {MARKER_BASELINE_PATH.relative_to(ROOT)}.")
        return
    check_required_files()
    check_changelog_fragments()
    check_template_context_sizes()
    check_language_policy()
    check_governed_review_worktree_contract()
    check_governed_lifecycle_text()
    check_json()
    check_stop_code_registry()
    check_plugin_version()
    meridian.load_retired_text_registry(ROOT)
    check_capability_catalog()
    check_migrations()
    check_catalog_surface_migrations()
    check_releases()
    check_bash()
    check_local_markdown_links()
    check_capability_marker_baselines()
    check_self_hosting_baseline()
    check_managed_digests()
    check_no_machine_paths()
    check_no_private_names()
    print("Meridian repository checks passed.")


if __name__ == "__main__":
    main()
