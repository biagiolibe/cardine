"""Pure seven-step preview, locations and bounded implementation adapters.

Preview remains read-only. The implementation adapters verify receipt-backed
progress or perform one owned delivery for dispatcher composition. Resolution
never interprets editable run metadata as verified progress.
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
    if value["stop"] is not None:
        entry = load_stop_registry().get(value["stop"]["code"])
        if not entry or entry["resolution"] != "guardrail" or entry["human_decision"] is not True:
            raise ValueError("only registered human guardrails can block")
    if value["stop"] is not None and (value["next"]["command"] != value["stop"]["resume"]
                                       or value["next"]["argv"] != value["stop"]["resume_argv"]):
        raise ValueError("guardrail resume must equal next")
    for reference in [value["next"], *([dict(command=value["stop"]["resume"],
                                             argv=value["stop"]["resume_argv"])] if value["stop"] else [])]:
        if reference is not None and reference["command"] != shlex.join(reference["argv"]):
            raise ValueError("run command does not match quoted argv")


def render_output(result: dict) -> str:
    """Stable byte representation; preview has no clock, journal or subprocess."""
    from cardine.stops.render import render_run_output
    return render_run_output(result, validate_output)


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


def deliver_run_implementation(locations: RunLocations) -> dict:
    """Bounded step-three adapter; validation and acceptance remain separate."""
    from cardine.lifecycle.commands import execution_deliver
    return execution_deliver(locations.worktree, locations.task_id, implementation_only=True)


def implementation_delivery(locations: RunLocations) -> dict | None:
    """Read verified step-three progress; no prose, writes or caller pass flags."""
    from cardine.lifecycle.delivery import verify_delivery
    from cardine.lifecycle.execution import _execution_location, _execution_owned_paths, _execution_state
    from cardine.lifecycle.scope import enforce_scope
    root = locations.worktree
    inspection = _execution_location(root, locations.task_id)
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('implementation progress requires the canonical task worktree')
    from cardine.lifecycle.delivery import _operation_path
    from cardine.lifecycle.receipts import _load_intent, require_authority
    operation = _operation_path(root, locations.task_id)
    intent = None
    if operation.exists():
        intent = _load_intent(operation)
        if (intent['task_id'] != locations.task_id or intent['root'] != str(root.resolve())
                or intent['base'] != str(inspection['base_commit'])
                or intent['authority'] != require_authority(root)):
            raise CardineError('implementation progress has a foreign delivery operation')
        if intent['result'] != 'verified':
            return None  # The dispatcher must reconcile the owned operation first.
    state = _execution_state(root, locations.task_id)
    base = str(inspection['base_commit'])
    enforce_scope(root, state, base, owned=_execution_owned_paths(root, locations.task_id))
    result = verify_delivery(root, state, base)
    if result is not None and intent is not None and result['commit'] != intent['commit']:
        raise CardineError('implementation delivery result identity changed')
    return result


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
    from cardine.shared.errors import CardineStop
    from cardine.stops.render import emit_run
    locations = None
    try:
        args = parser.parse_args(argv)
        locations = resolve_run_locations(args.task_id, args.project)
    except (CardineError, OSError, ValueError) as error:
        result = envelope("", "", step=None, diagnostics=[dict(code="INVALID_INVOCATION", message=str(error))])
        emit_run(result, validate_output)
        return 64
    try:
        state = read_task_state(locations.primary, locations.task_id, "single",
                                stop_factory=stop_error, require_contract=True)
        if "contract" not in state:
            raise CardineError("missing frozen contract; preview cannot import task prose")
        # RE3b composes measured validation only after a verified delivery.
        # Earlier contract/preparation dispatch and later landing adapters stay
        # independent; editable progress cannot skip those receipt checks.
        result = run_validation_step(locations)
        if result is None:
            result = resolve_run(RunFacts(locations.task_id, locations.primary, state["status"]))
    except CardineStop as error:
        result = diagnostic_result(locations, error)
    except Exception as error:
        # An unknown failure carries no ownership proof and must never suggest
        # successful progress or an automatic repair inferred from its prose.
        result = diagnostic_result(locations, stop_error("COMMAND_REFUSED", str(error)))
    return emit_run(result, validate_output)


def run_validation_step(locations: RunLocations) -> dict | None:
    """Recover missing task evidence and return the review or C6 boundary."""
    from cardine.lifecycle.validation import operation_path, run_task_validation
    from cardine.lifecycle.execution import _execution_state
    from cardine.lifecycle.model import WorkRequest
    from cardine.lifecycle import receipts
    root, task_id = locations.worktree, locations.task_id
    if not root.is_dir():
        return None
    state = _execution_state(root, task_id) if not receipts.pending_operation(root, task_id) else None
    contract = state['contract'] if state else {}
    request = WorkRequest('implementer', root,
        receipts.digest(receipts.encoded(contract)),
        tuple(contract.get('expectedCodeSurface', [])), tuple(contract.get('deliverables', [])),
        tuple(contract.get('validation', {}).get('baseline', [])), ('committed implementation delivery',))
    pending = operation_path(root, task_id).exists()
    if not pending and implementation_delivery(locations) is None:
        return resolve_run(RunFacts(task_id, locations.primary, 'in_progress',
                           contract_ready=True, worktree_ready=True, implementation_work=request))
    from cardine.shared.errors import CardineStop
    try:
        progress = run_task_validation(root, task_id)
    except CardineStop as error:
        if error.code != 'ACCEPTANCE_UNMET':
            raise
        result = resolve_run(RunFacts(task_id, locations.primary, 'in_progress',
            contract_ready=True, worktree_ready=True, validation_failed=True, implementation_work=request))
        result['diagnostics'] = [dict(code=error.code, message=error.detail)]
        return result
    state = _execution_state(root, task_id)
    if not contract:
        contract = state['contract']
        request = WorkRequest('implementer', root, receipts.digest(receipts.encoded(contract)),
            tuple(contract.get('expectedCodeSurface', [])), tuple(contract.get('deliverables', [])),
            tuple(contract['validation']['baseline']), ('committed implementation delivery',))
    passed = progress['phase'] == 'passed'
    from cardine.tasks.validation import host_observations_complete
    if passed and not host_observations_complete(contract, progress):
        result = resolve_run(RunFacts(task_id, locations.primary, state['status'],
            contract_ready=True, worktree_ready=True, validation_failed=True, implementation_work=request))
        result['diagnostics'] = [dict(code='ACCEPTANCE_UNMET',
            message='An enforced host profile needs a matching declared validation command and passing observation')]
        return result
    result = resolve_run(RunFacts(task_id, locations.primary, state['status'],
        contract_ready=True, worktree_ready=True, implementation_delivered=True,
        validation_passed=passed, validation_failed=not passed,
        implementation_work=request,
        review_required=state['contract']['options']['review'] == 'required'))
    result['action'] = 'C6' if result['step'] == 'candidate' else 'task-validation'
    result['evidence'] = [dict(kind='task-validation', path=progress['evidence'], identity=progress['attemptId'])]
    if not passed:
        result['diagnostics'] = [dict(code='VALIDATION_FAILED', message=json.dumps(progress['runs']))]
    return result


def diagnostic_result(locations: RunLocations, error, *, step: str = "contract") -> dict:
    """Adapt a cause-classified error, preserving its exact recovery command."""
    from cardine.stops.render import outcome_for_code
    from cardine.stops.render import stop_error
    if error.code not in load_stop_registry() or error.detail is None or error.resume is None:
        error = stop_error("COMMAND_REFUSED", "unknown or untyped diagnostic: " + error.code)
    detail = error.detail
    outcome = outcome_for_code(error.code)
    run_argv = ["cardine", "run", locations.task_id, "--project", str(locations.primary)]
    resume_argv = shlex.split(error.resume()) if outcome == "next" else run_argv
    # Historical advice is not an executable recovery. Keep it in diagnostics
    # and re-enter the owned resolver; later rows implement its bounded step.
    if not resume_argv or resume_argv[0] not in {"cardine", "git"}:
        resume_argv = run_argv
    next_command = command_reference(resume_argv, "Resolve " + error.code)
    stop = None
    if outcome == "blocked":
        # Guardrails recheck the same task after the missing decision. Internal
        # recoveries instead retain their cause-specific command unchanged.
        next_command = command_reference(
            ["cardine", "run", locations.task_id, "--project", str(locations.primary)],
            "Recheck the guardrail after the required decision")
        stop = dict(code=error.code, resolution="guardrail", human_decision=True,
                    detail=detail, resume=next_command["command"], resume_argv=next_command["argv"])
    return envelope(locations.task_id, str(locations.primary), step=step, outcome=outcome,
                    next_command=next_command, stop=stop,
                    diagnostics=[dict(code=error.code, message=detail)])
