"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES, names

import hashlib
import json
from pathlib import Path
import re

from cardine.shared.errors import CardineError
from cardine.tasks.contract_fields import HUMAN_CONTRACT_FIELDS, contract_hash, frozen_human_fields
from cardine.stops.render import stop_error
from cardine.tasks.evidence import validation_commands
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_task_identity
from cardine.shared.project import parse_project_declaration, read_project_declaration
from cardine.shared.project import resolve_project_configuration, project_validation_commands
from cardine.tasks.evidence import require_named_validation_commands
from copy import deepcopy


def _contract_field(text: str, field: str) -> str | None:
    """Read an inline blueprint field or a nonempty level-two section."""
    inline = re.search(
        rf"^(?:>\s*)?(?:\*\*)?{re.escape(field)}(?:\*\*)?:[ \t]*(.+)$",
        text, re.MULTILINE | re.IGNORECASE,
    )
    if inline:
        return inline.group(1).strip().strip("`") or None
    section = re.search(
        rf"^## [^\w\n]*{re.escape(field)}\s*$\n(.*?)(?=^## |\Z)",
        text, re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return section.group(1).strip() or None if section else None


def task_contract_options(text: str) -> dict[str, object]:
    """Options is a JSON object, inline or in a fenced ## Options section.

    Review also accepts the historical REQUIRED/NOT_REQUIRED field spelling.
    Conflicting duplicate declarations are rejected rather than guessed.
    """
    raw = _contract_field(text, "Options")
    if raw and raw.startswith("```json\n") and raw.endswith("```"):
        raw = raw[len("```json\n"):-3]
    try:
        options = json.loads(raw) if raw is not None else {}
    except json.JSONDecodeError as error:
        raise CardineError("task Options must be a JSON object") from error
    if not isinstance(options, dict):
        raise CardineError("task Options must be a JSON object")
    review = _contract_field(text, "Review")
    if review is not None:
        review = review.lower()
        if "review" in options and options["review"] != review:
            raise CardineError("task Review conflicts with Options.review")
        options["review"] = review
    return options


def resolve_task_contract(project_root: Path, task_id: str, *, text: str | None = None,
                          identity=None) -> dict[str, object]:
    """Build the creation snapshot reused by work item 7's task-new adapter.

    This function never writes state or revises an existing snapshot. Category:
    Quick selects the minimal registered record; its class remains standard.
    Policy is preset -> project defaults -> explicit task Options/Review.
    """
    identity = identity or resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    if text is None:
        text = identity.task_path.read_text(encoding="utf-8")
    if _contract_field(text, "ID") != identity.canonical_id:
        raise CardineError(f"task contract ID must be {identity.canonical_id!r}")
    declaration = read_project_declaration(project_root)
    configuration = resolve_project_configuration(project_root)
    options = {**configuration["taskDefaults"], **task_contract_options(text)}
    # Reuse project type, unknown-key and CI checks after task overrides.
    parse_project_declaration({**declaration, "taskDefaults": options})
    task_class = (_contract_field(text, "Class") or "standard").lower()
    if task_class not in ("standard", "spike"):
        raise CardineError("task Class must be standard or spike")
    quick = (_contract_field(text, "Category") or "").lower() == "quick"
    required = ["Dependencies"]
    if task_class == "spike":
        required.extend(SPIKE_PREFLIGHT_FIELDS)
    else:
        required.extend(("Objective", "Acceptance Criteria", "Validation"))
    if not quick:
        required.extend(("Priority", "Estimate", "Out of scope"))
        if not (_contract_field(text, "Relevant Files") or _contract_field(text, "Technical Context")):
            required.append("Relevant Files")
        if not re.search(r"^# \S.+$", text, re.MULTILINE) and not _contract_field(text, "Title"):
            required.append("Title")
    if options["authorityRequired"]:
        required.append("Authority")
    if options["expectedCodeSurfaceRequired"]:
        required.append("Expected code surface")
    missing = [field for field in required if not _contract_field(text, field)]
    if missing:
        raise CardineError("task contract missing required fields: " + ", ".join(missing))
    validate_host_impact_declaration(text)
    require_named_validation_commands(text)
    validation = deepcopy(configuration.get("validation"))
    project_validation_commands(configuration)  # Absent is not explicit empty.
    task_commands = validation_commands(text)
    for key, command in task_commands.items():
        if key in validation["commands"] and validation["commands"][key] != command:
            raise CardineError(f"task validation ID {key!r} conflicts with the project command")
        validation["commands"][key] = command
        if key not in validation["baseline"]:
            validation["baseline"].append(key)
    # Keep literal commands and IDs; candidates always include the diff check.
    diff_id = next((key for key, command in validation["commands"].items()
                    if command == "git diff --check"), None)
    if diff_id is None:
        diff_id = "candidate-diff-check"
        while diff_id in validation["commands"]:
            diff_id += "-diff"
        validation["commands"][diff_id] = "git diff --check"
    for references in validation["candidate"].values():
        if diff_id not in references and diff_id not in validation["baseline"]:
            references.append(diff_id)
    return {
        **resolve_human_fields(project_root, identity, text, task_class),
        "preset": configuration["preset"], "class": task_class,
        "projectDigest": "sha256:" + hashlib.sha256(
            json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "options": options, "validation": validation,
        "ci": deepcopy(configuration.get("ci", "none")),
        "validationScoping": deepcopy(configuration.get("validationScoping", [])),
    }


def _field(text: str, name: str) -> str:
    match = re.search(rf"^(?:>\s*)?(?:-\s*)?(?:\*\*)?{name}(?:\*\*)?:\s*(.*)$", text, re.M | re.I)
    return match.group(1).strip().strip('`') if match else ""


def _dependencies(text: str) -> list[str]:
    section = re.search(r'^## Dependencies\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not section:
        return []
    body = section.group(1)
    raw = _field(body, 'Depends on') or body.strip()
    raw = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', raw)
    result = []
    for item in re.split(r'[,\n]', raw):
        item = item.strip().removeprefix('- ').strip().strip('`').strip()
        if item.lower().strip(' .') in ('', 'none', '—', '-'):
            continue
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', item):
            raise ValueError(f'invalid dependency declaration: {item!r}')
        if item not in result:
            result.append(item)
    return result


def resolve_human_fields(project_root, identity, text, task_class):
    """Parse human intent once; absent optional labels have explicit empty values."""
    from cardine.shared.authority import authority_entries
    try:
        dependencies = _dependencies(text)
    except ValueError as error:
        raise CardineError(str(error)) from error
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    deliverable = _contract_field(text, "Deliverable") or ""
    paths = []
    if task_class == "spike":
        for match in re.finditer(r"`(docs/[^`]+)`|(?<!\S)(docs/[^\s`]+)", deliverable):
            path = (match.group(1) or match.group(2).rstrip(".,;")).split("#", 1)[0]
            paths.append(path)
    for path in paths:
        if ".." in Path(path).parts:
            raise CardineError(f"unsafe spike deliverable path: {path}")
    return {
        "dependencies": dependencies,
        "title": _contract_field(text, "Title") or (heading.group(1).strip() if heading else identity.canonical_id),
        "priority": _contract_field(text, "Priority") or "",
        "phase": _contract_field(text, "Phase") or "",
        "origin": _contract_field(text, "Origin") or "",
        "deliverables": list(dict.fromkeys(paths)),
        "authority": list(dict.fromkeys(authority_entries(text))),
        "recordPath": identity.task_path.relative_to(Path(project_root).resolve()).as_posix(),
    }


def profile_digest(project_root: Path) -> str:
    profile = project_root / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
    if not profile.is_file():
        raise stop_error(
            "EXECUTION_PROFILE_MISSING",
            "rule: the execution contract derives from the project profile; source checked: "
            "docs/EXECUTION_EVIDENCE_PROFILE.md; expected: the file exists; found: no such file",
        )
    return hashlib.sha256(profile.read_bytes()).hexdigest()


def contract_digest(text: str) -> str | None:
    match = re.search(r"^- Profile revision: `sha256:([0-9a-f]{64})`$", text, re.MULTILINE)
    return match.group(1) if match else None


EXECUTION_COMMANDS_VALUE = "required via cardine execution"
EXECUTION_COMMANDS_LINE = f"- Execution commands: `{EXECUTION_COMMANDS_VALUE}`"


def contract_requires_execution_commands(text: str) -> bool:
    return EXECUTION_COMMANDS_LINE in text


PREFLIGHT_HEADINGS = ("Authority", "Validation")


NORMAL_PREFLIGHT_HEADINGS = ("Expected code surface",)


SPIKE_PREFLIGHT_FIELDS = ("Question", "Timebox", "Deliverable")


HANDOFF_FIELDS = (
    "Files changed",
    "Validation",
    "Validation skips",
    "Manual verification",
    "Acceptance criteria",
    "Isolated exploration",
    "Blockers/deviations",
)


EXECUTION_EVIDENCE_PATH = PRODUCT_NAMES.execution_evidence_path


HOST_IMPACT_STATES = ("enforced", "advisory", "unsupported", "unverified")


HOST_IMPACT_EVIDENCE_CATEGORIES = ("Static", "Host execution", "Manual activation")


def host_impact_section(text: str) -> str | None:
    """Return the optional host-impact declaration from a task record.

    Records created before the Task 044 blueprint deliberately have no such
    section.  They remain valid historical inputs rather than being rewritten
    solely to satisfy a newly introduced lifecycle gate.
    """
    section = re.search(r"^## Host impact\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return section.group(1) if section else None


def host_impact_field(section: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(\S.*)$", section, re.MULTILINE)
    return match.group(1).strip() if match else None


def host_impact_required_profiles(section: str) -> list[tuple[str, str]]:
    """Validate a REQUIRED declaration and return its claimed profile states."""
    if not host_impact_field(section, "Policy outcome"):
        raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "REQUIRED declaration is missing Policy outcome")

    table = re.search(
        r"^\|\s*Profile\s*\|\s*Before\s*\|\s*Intended after\s*\|\s*Activation preconditions\s*\|\s*Fallback\s*\|\s*$\n"
        r"^\|(?:\s*:?-+\s*\|){4}\s*:?-+\s*\|\s*$\n"
        r"((?:^\|.*\|\s*$\n?)+)",
        section,
        re.MULTILINE,
    )
    if table is None:
        raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "REQUIRED declaration is missing the profile table")

    profiles: list[tuple[str, str]] = []
    for line in table.group(1).splitlines():
        if not line.strip():
            continue
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        if len(values) != 5:
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "profile table row must contain five fields")
        profile, before, intended_after, activation, fallback = values
        for name, value in (
            ("Profile", profile),
            ("Before", before),
            ("Intended after", intended_after),
            ("Activation preconditions", activation),
            ("Fallback", fallback),
        ):
            if not value:
                raise stop_error("HOST_IMPACT_DECLARATION_INVALID", f"profile table is missing {name}")
        for name, value in (("Before", before), ("Intended after", intended_after)):
            if value not in HOST_IMPACT_STATES:
                raise stop_error(
                    "HOST_IMPACT_DECLARATION_INVALID",
                    f"profile {profile!r} has invalid {name} state {value!r}; accepted: {', '.join(HOST_IMPACT_STATES)}",
                )
        profiles.append((profile, intended_after))

    for category in HOST_IMPACT_EVIDENCE_CATEGORIES:
        if not re.search(rf"^- {re.escape(category)}:\s*\S+", section, re.MULTILINE):
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", f"REQUIRED declaration is missing {category} evidence plan")
    return profiles


def validate_host_impact_declaration(text: str) -> list[tuple[str, str]]:
    """Validate a Task 044 declaration, retaining pre-migration task records."""
    section = host_impact_section(text)
    if section is None:
        return []
    classification = host_impact_field(section, "Classification")
    if classification == "NOT_APPLICABLE":
        if not host_impact_field(section, "Rationale"):
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "NOT_APPLICABLE declaration is missing Rationale")
        return []
    if classification == "REQUIRED":
        return host_impact_required_profiles(section)
    raise stop_error(
        "HOST_IMPACT_DECLARATION_INVALID",
        f"Classification must be NOT_APPLICABLE or REQUIRED; found: {classification!r}",
    )


def verify_host_impact_completion_evidence(text: str) -> None:
    """Require profile-specific durable evidence for each enforced claim."""
    section = host_impact_section(text)
    if section is None:
        return
    enforced_profiles = [profile for profile, state in validate_host_impact_declaration(text) if state == "enforced"]
    if not enforced_profiles:
        return
    evidence = {
        match.group(1).strip()
        for match in re.finditer(r"^- \[([^\]]+)\]:\s*\S+", section, re.MULTILINE)
    }
    missing = [profile for profile in enforced_profiles if profile not in evidence]
    if missing:
        raise stop_error(
            "HOST_IMPACT_EVIDENCE_MISSING",
            "enforced profile is missing Completion evidence: " + ", ".join(missing),
        )


def execution_entries(project_root: Path, task_id: str) -> list[dict[str, object]]:
    path = project_root / names().execution_evidence_path
    if not path.is_file():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CardineError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    entries = state.get(canonical_id, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise CardineError(f"invalid execution evidence entries for {task_id}: {path}")
    return entries


def verify_validation_skips(report_text: str, task_id: str) -> None:
    """Reject validation failures that a handoff's skip declaration cannot excuse."""
    reported = re.search(r"^- Validation skips:\s*(.+)$", report_text, re.MULTILINE)
    assert reported is not None  # HANDOFF_FIELDS has already checked its presence.
    value = reported.group(1).strip()
    validation = re.search(r"^- Validation:\s*(.+)$", report_text, re.MULTILINE)
    assert validation is not None  # HANDOFF_FIELDS has already checked its presence.
    failed_validation = re.search(r"\bexit\s+[1-9][0-9]*\b", validation.group(1))

    if value.lower() == "none":
        if failed_validation:
            raise stop_error(
                "HANDOFF_VALIDATION_FAILING",
                f"rule: a failing validation needs a named skip; field checked: Validation; accepted: no "
                f"`exit <non-zero>`; found: `{failed_validation.group(0)}` with Validation skips: none",
                task_id=task_id,
            )
        return

    if failed_validation:
        raise stop_error(
            "HANDOFF_VALIDATION_FAILING",
            f"rule: a named skip does not make a failing validation pass; field checked: Validation; "
            f"accepted: no `exit <non-zero>`; found: `{failed_validation.group(0)}` with Validation skips: {value}",
            task_id=task_id,
        )


def verify_execution_evidence(project_root: Path, task_id: str, report_text: str) -> None:
    """Require report claims to be backed by durable, task-declared evidence."""
    task_text = find_task_file(project_root, task_id).read_text(encoding="utf-8")
    entries = execution_entries(project_root, task_id)
    commands = validation_commands(task_text)
    missing_validations = [
        command_id for command_id, command in commands.items()
        if not any(
            entry.get("id") == command_id
            and entry.get("command") == command
            and entry.get("exitStatus") == 0
            for entry in entries
        )
    ]
    if missing_validations:
        raise stop_error(
            "HANDOFF_VALIDATION_EVIDENCE_MISSING",
            f"rule: every declared validation needs a successful durable record; source checked: "
            f"{names().execution_evidence_path.as_posix()} for {task_id}; accepted: an entry with the declared id and "
            f"command and exitStatus 0; missing for: " + ", ".join(missing_validations),
            task_id=task_id,
        )


def check_handoff(project_root: Path, task_id: str, report: Path) -> str:
    """Reject incomplete completion evidence before it can be used as a handoff."""
    if not report.is_file():
        raise stop_error(
            "HANDOFF_REPORT_MISSING",
            f"rule: the handoff check reads a completion report; source checked: {report}; "
            "expected: an existing file; found: no such file",
            task_id=task_id,
        )
    text = report.read_text(encoding="utf-8")
    missing = [field for field in HANDOFF_FIELDS if not re.search(rf"^- {re.escape(field)}:\s*\S+", text, re.MULTILINE)]
    if missing:
        labels = re.findall(r"^- ([^:\n]+):", text, re.MULTILINE)
        malformed = {
            field: label for field in missing for label in labels
            if label not in HANDOFF_FIELDS and re.match(rf"{re.escape(field)}(?![A-Za-z0-9])", label)
        }
        if malformed:
            raise stop_error(
                "HANDOFF_FIELD_FORMAT",
                f"rule: a required field's name must be followed directly by the colon; source checked: {report.name}; "
                "accepted form: `- <Field>: <value>`; found: "
                + "; ".join(f"`- {label}:` (expected `- {field}: <value>`)" for field, label in malformed.items()),
                task_id=task_id,
            )
        raise stop_error(
            "HANDOFF_FIELDS_MISSING",
            f"rule: every required field needs a non-empty value; source checked: {report.name}; "
            "accepted form: `- <Field>: <value>`; required: " + ", ".join(HANDOFF_FIELDS)
            + "; missing: " + ", ".join(missing),
            task_id=task_id,
        )
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    if f"Completion Report — {canonical_id}" not in text:
        heading = re.search(r"Completion Report — (\S+)", text)
        raise stop_error(
            "HANDOFF_TASK_MISMATCH",
            f"rule: the report must identify its task; source checked: {report.name}; "
            f"accepted: `Completion Report — {canonical_id}`; found: "
            + (f"`{heading.group(0)}`" if heading else "no Completion Report heading"),
            task_id=task_id,
        )
    verify_validation_skips(text, task_id)
    verify_execution_evidence(project_root, task_id, text)
    return f"Handoff evidence complete for {task_id}: {report}"


def default_handoff_path(project_root: Path, task_id: str) -> Path:
    return resolve_task_identity(project_root, task_id, "existing").handoff_path
