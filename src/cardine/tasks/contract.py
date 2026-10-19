"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from cardine.shared.errors import MeridianError
from cardine.stops.render import stop_error
from cardine.tasks.evidence import validation_commands
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_task_identity


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


def contract_requires_execution_commands(text: str) -> bool:
    return "- Execution commands: `required via meridian execution`" in text


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


EXECUTION_EVIDENCE_PATH = Path(".meridian/execution-evidence.json")


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
    path = project_root / EXECUTION_EVIDENCE_PATH
    if not path.is_file():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    entries = state.get(canonical_id, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise MeridianError(f"invalid execution evidence entries for {task_id}: {path}")
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
            f"{EXECUTION_EVIDENCE_PATH.as_posix()} for {task_id}; accepted: an entry with the declared id and "
            f"command and exitStatus 0; missing for: " + ", ".join(missing_validations),
            task_id=task_id,
        )

    investigations = [entry for entry in entries if entry.get("kind") == "investigation"]
    reported = re.search(r"^- Isolated exploration:\s*(.+)$", report_text, re.MULTILINE)
    assert reported is not None  # HANDOFF_FIELDS has already checked its presence.
    value = reported.group(1).strip()
    if not investigations:
        if not re.match(r"(?i)(?:none|no)(?![A-Za-z0-9])", value):
            raise stop_error(
                "HANDOFF_EXPLORATION_MISMATCH",
                f"rule: with no recorded investigation the report must say there was none; field checked: "
                f"Isolated exploration against {EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: `none`, or text "
                f"starting with `none` or `no`; found: {value!r}; expected `none` (or record the investigation)",
                task_id=task_id,
            )
        return
    if value.lower() == "none":
        raise stop_error(
            "HANDOFF_EXPLORATION_MISMATCH",
            f"rule: recorded investigations must be reported; field checked: Isolated exploration against "
            f"{EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: a summary of each recorded investigation; "
            f"found: `none` with {len(investigations)} recorded",
            task_id=task_id,
        )
    missing_summaries = [
        str(entry.get("question", ""))
        for entry in investigations
        if str(entry.get("question", "")) not in report_text
        or str(entry.get("finding", "")) not in report_text
    ]
    if missing_summaries:
        raise stop_error(
            "HANDOFF_EXPLORATION_SUMMARY_MISSING",
            f"rule: the report must contain each recorded question and finding; source checked: "
            f"{EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: the exact question and finding text; "
            f"missing the question or finding of: " + "; ".join(missing_summaries),
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
