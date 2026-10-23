"""Pure seven-step preview and read-only invocation location resolution.

No dispatcher effects are implemented here. Receipt readers/writers and effect
dispatch belong to the subsequent run-engine rows. Resolution never interprets
editable run metadata as verified progress.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path
from collections.abc import Iterable

from cardine.lifecycle.model import OUTCOMES, STEPS, RunFacts, RunLocations
from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir, canonical_project_root
from cardine.stops.registry import load_stop_registry
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.paths import task_worktree_path
from cardine.worktree.storage import resolve_worktree_root


def command_reference(argv: Iterable[str], reason: str) -> dict:
    values = list(argv)
    if not values or any(not isinstance(item, str) or "\0" in item for item in values):
        raise ValueError("command argv must contain non-NUL strings")
    return {"command": shlex.join(values), "argv": values, "reason": reason}


def envelope(task_id: str, project: str, *, step: str | None,
             outcome: str = "next", action: str = "none", next_command: dict | None = None,
             stop: dict | None = None, work: dict | None = None,
             evidence: list | None = None, diagnostics: list | None = None,
             retry_after_seconds: int = 0) -> dict:
    """Build the closed v1 envelope and enforce cross-field invariants."""
    if outcome not in OUTCOMES or step not in (*STEPS, None):
        raise ValueError("unknown run outcome or step")
    if (outcome == "blocked") != (stop is not None):
        raise ValueError("only blocked requires a stop")
    if outcome == "done" and next_command is not None:
        raise ValueError("done cannot have a next command")
    if step is not None and outcome != "done" and next_command is None:
        raise ValueError("a resolved nonterminal task requires a next command")
    if type(retry_after_seconds) is not int or retry_after_seconds < 0 or (
            retry_after_seconds and outcome != "waiting"):
        raise ValueError("only waiting may request a positive polling interval")
    if stop is not None:
        entry = load_stop_registry().get(stop.get("code"))
        if not entry or entry["resolution"] != "guardrail" or not entry["human_decision"]:
            raise ValueError("only registered human guardrails can block")
        if (stop.get("resolution") != "guardrail" or stop.get("human_decision") is not True
                or next_command is None or next_command["argv"] != stop.get("resume_argv")
                or next_command["command"] != stop.get("resume")):
            raise ValueError("blocked next command must equal its guardrail resume")
    value = dict(version=1, task_id=task_id, project=project, outcome=outcome,
                step=step, action=action, next=next_command, stop=stop, work=work,
                evidence=[] if evidence is None else evidence,
                diagnostics=[] if diagnostics is None else diagnostics,
                retry_after_seconds=retry_after_seconds)
    validate_output(value)
    return value


def validate_output(value: dict) -> None:
    """Enforce closed typed objects without adding a runtime dependency."""
    from cardine.tasks.state import _validate_schema
    schema_path = Path(__file__).resolve().parents[3] / "schemas/run-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def check(item, rule):
        # The task-state validator supplies strict JSON types and closed keys.
        _validate_schema(item, rule, "run")
        if "const" in rule and (type(item) is not type(rule["const"]) or item != rule["const"]):
            raise ValueError("run constant mismatch")
        if "not" in rule:
            try:
                check(item, rule["not"])
            except ValueError:
                pass
            else:
                raise ValueError("run forbidden value")
        if "anyOf" in rule:
            for choice in rule["anyOf"]:
                try:
                    check(item, choice)
                    break
                except ValueError:
                    pass
            else:
                raise ValueError("run value matches no allowed type")
        for child in rule.get("allOf", []):
            check(item, child)
        if "if" in rule:
            try:
                check(item, rule["if"])
            except ValueError:
                check(item, rule.get("else", {}))
            else:
                check(item, rule.get("then", {}))
        if isinstance(item, dict):
            for name, child in rule.get("properties", {}).items():
                if name in item:
                    check(item[name], child)
        if isinstance(item, list):
            if len(item) < rule.get("minItems", 0):
                raise ValueError("run array is empty")
            for child in item:
                check(child, rule.get("items", {}))

    check(value, schema)
    if value["step"] is None and (value["next"] is not None or value["stop"] is not None):
        raise ValueError("unresolved invocation cannot fabricate a next command")
    if value["stop"] is not None and (value["next"]["command"] != value["stop"]["resume"]
                                       or value["next"]["argv"] != value["stop"]["resume_argv"]):
        raise ValueError("guardrail resume must equal next")
    for reference in [value["next"], *([dict(command=value["stop"]["resume"],
                                             argv=value["stop"]["resume_argv"])] if value["stop"] else [])]:
        if reference is not None and reference["command"] != shlex.join(reference["argv"]):
            raise ValueError("run command does not match quoted argv")


def render_output(result: dict) -> str:
    """Stable byte representation; preview has no clock, journal or subprocess."""
    validate_output(result)
    return json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def resolve_run(facts: RunFacts) -> dict:
    """Choose one bounded next step without changing inputs or executing effects."""
    argv = ["cardine", "run", facts.task_id, "--project", str(facts.project)]

    def result(step, reason, *, outcome="next", action="none", poll=0, stop=None):
        request = facts.implementation_work if step == "implementation" else None
        return envelope(facts.task_id, str(facts.project), step=step, outcome=outcome,
                        action=action, next_command=command_reference(argv, reason),
                        stop=stop, retry_after_seconds=poll,
                        work=request.as_json() if request else None)

    if facts.status == "cancelled":
        return envelope(facts.task_id, str(facts.project), step="landing", outcome="done")
    if facts.status == "done":
        if facts.cleanup_pending or not facts.landing_complete:
            return result("landing", "Finish pending delivery and cleanup")
        return envelope(facts.task_id, str(facts.project), step="landing", outcome="done")
    if facts.pending_step:
        return result(facts.pending_step, "Reconcile the owned interrupted operation")
    if facts.guardrail:
        guard = facts.guardrail
        resume = command_reference(argv, "Recheck the guardrail after the required decision")
        stop = dict(code=guard.code, resolution="guardrail", human_decision=True,
                    detail=guard.detail, resume=resume["command"], resume_argv=resume["argv"])
        return result(guard.step, resume["reason"], outcome="blocked", stop=stop)
    if not facts.contract_ready:
        return result("contract", "Check the frozen contract, dependencies, policy and scope")
    if not facts.worktree_ready or facts.status == "queued":
        return result("worktree", "Prepare and verify the canonical task worktree")
    if facts.validation_failed or facts.review_changes_requested:
        return result("implementation", "Repair the delivered implementation", outcome="iterate")
    if not facts.implementation_delivered:
        return result("implementation", "Obtain committed implementation and acceptance evidence")
    if not facts.validation_passed:
        return result("validation", "Run the complete current validation command set")
    if facts.review_required and not facts.review_approved:
        if facts.review_pending:
            return result("review", "Wait for the independent review", outcome="waiting", poll=10)
        review_argv = ["cardine", "review", facts.task_id, "--project", str(facts.project)]
        return envelope(facts.task_id, str(facts.project), step="review",
                        next_command=command_reference(review_argv, "Obtain independent approval"),
                        work=facts.review_work.as_json() if facts.review_work else None)
    if facts.ci_pending:
        return result("candidate", "Poll required CI checks for the delivered source", outcome="waiting", poll=10)
    if not facts.candidate_validated:
        reason = "Prepare and validate the current direct candidate"
        if not facts.review_required:
            reason = "Review is not required; " + reason[0].lower() + reason[1:]
        return result("candidate", reason)
    return result("landing", "Finalize, push, verify and clean up delivery")


def resolve_run_locations(task_id: str, project: Path | None = None, *,
                          cwd: Path | None = None, registered_projects: Iterable[Path] = (),
                          worktree_root: Path | None = None) -> RunLocations:
    """Read locations from either checkout or unique supplied registry entries.

    Registry discovery is supplied by the machine registry reader; this function
    never scans arbitrary directories or creates a registration/configuration.
    """
    def identify(path):
        primary = canonical_project_root(path)
        common = canonical_git_common_dir(path)
        if common != canonical_git_common_dir(primary):
            raise CardineError("project/common-directory identity mismatch")
        identity = resolve_task_identity(primary, task_id, "existing", check_queue_links=False)
        return primary, common, identity

    if project is not None:
        primary, common, identity = identify(project.expanduser().resolve())
    else:
        enclosing = None
        try:
            enclosing = canonical_project_root(cwd or Path.cwd())
        except CardineError:
            pass
        if enclosing is not None:
            primary, common, identity = identify(enclosing)
        else:
            matches = {}
            for candidate in registered_projects:
                try:
                    item = identify(candidate)
                except CardineError:
                    continue
                matches[item[1]] = item
            if len(matches) != 1:
                raise CardineError("missing or ambiguous project/task identity; supply --project")
            primary, common, identity = next(iter(matches.values()))
    root = resolve_worktree_root(worktree_root).path
    return RunLocations(identity.canonical_id, primary, common, root,
                        task_worktree_path(primary, root, identity.canonical_id))


def run_preview_cli(argv: list[str]) -> int:
    """RE1a adapter: preview only; later rows supply verified progress adapters.

    Existing state is schema-validated. No receipt-less run fields are accepted
    as readiness, and no absent state is created or imported from a record.
    """
    import argparse
    from cardine.shared.layout import names
    from cardine.tasks.state import read_task_state
    from cardine.stops.render import stop_error

    class InvocationParser(argparse.ArgumentParser):
        def error(self, message):
            raise CardineError(message)

    parser = InvocationParser(prog="cardine run")
    parser.add_argument("task_id")
    parser.add_argument("--project", type=Path)
    try:
        args = parser.parse_args(argv)
        locations = resolve_run_locations(args.task_id, args.project)
        state = read_task_state(locations.primary, locations.task_id, "single",
                                stop_factory=stop_error, require_contract=True)
        if "contract" not in state:
            raise CardineError("missing frozen contract; preview cannot import task prose")
        # Progress verification is deliberately not inferred from editable JSON.
        result = resolve_run(RunFacts(locations.task_id, locations.primary, state["status"]))
    except (CardineError, OSError, ValueError) as error:
        result = envelope("", "", step=None, diagnostics=[dict(code="INVALID_INVOCATION", message=str(error))])
        print(render_output(result))
        return 64
    print(render_output(result))
    return 0
