"""Pure seven-step preview, locations and bounded implementation adapters.

Preview remains read-only. The implementation adapters verify receipt-backed
progress or perform one owned delivery for dispatcher composition. Resolution
never interprets editable run metadata as verified progress.
"""
from __future__ import annotations

from cardine.shared.git import scoped_command

import contextlib
import json
import os
import shlex
from pathlib import Path
from collections.abc import Iterable

from cardine.lifecycle.live import LiveLog
from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.model import OUTCOMES, STEPS, RunFacts, RunLocations
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.paths import framework_root
from cardine.stops.registry import load_stop_registry


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
    schema_path = framework_root() / "schemas/run-v1.schema.json"
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
        request = (facts.implementation_work if step == "implementation"
                   else facts.review_work if step == "review" else None)
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
        review_root = facts.review_work.worktree if facts.review_work else facts.project
        review_argv = ["cardine", "review", "verdict", facts.task_id, "APPROVE", "--owner",
                       "--project", str(review_root)]
        return envelope(facts.task_id, str(facts.project), step="review",
                        outcome="waiting" if facts.review_pending else "next",
                        retry_after_seconds=10 if facts.review_pending else 0,
                        next_command=command_reference(review_argv,
                            "Developer: choose APPROVE, CHANGES_REQUESTED or BLOCKED after review"),
                        work=facts.review_work.as_json() if facts.review_work else None)
    if facts.ci_pending:
        return result("candidate", "Poll required CI checks for the delivered source", outcome="waiting", poll=10)
    if not facts.candidate_validated:
        reason = "Prepare and validate the current direct candidate"
        if not facts.review_required:
            reason = "Review is not required; " + reason[0].lower() + reason[1:]
        return result("candidate", reason)
    return result("landing", "Finalize, push, verify and clean up delivery")


@scoped_command
def deliver_run_implementation(locations: RunLocations) -> dict:
    """Bounded step-three adapter; validation and acceptance remain separate."""
    from cardine.lifecycle.commands import execution_deliver
    return execution_deliver(locations.worktree, locations.task_id, implementation_only=True,
                             context=locations)


@scoped_command
def launch_run_work(locations: RunLocations, work, *, attempt: str, adapter) -> dict:
    """Launch one issued role through an explicitly injected host profile.

    No real-host fallback exists. RE4b consumes issued review sessions separately
    from their responses; a host completion never records a verdict here.
    """
    from cardine.hosts.launch import launch_work
    return launch_work(locations.worktree, locations.task_id, work, attempt=attempt,
                       adapter=adapter, context=locations)


def concrete_host_adapter(host: str, transport, credential: str):
    """Explicit factory for a concrete transport; there is still no default adapter or host fallback."""
    from cardine.hosts.launch import host_adapter
    return host_adapter(host, transport, credential)


@scoped_command
def implementation_delivery(locations: RunLocations) -> dict | None:
    """Read verified step-three progress; no prose, writes or caller pass flags."""
    from cardine.lifecycle.delivery import verify_delivery
    from cardine.lifecycle.execution import _execution_location, _execution_owned_paths, _execution_state
    from cardine.lifecycle.scope import enforce_scope
    root = locations.worktree
    inspection = _execution_location(root, locations.task_id, context=locations)
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('implementation progress requires the canonical task worktree')
    from cardine.lifecycle.delivery import _operation_path
    from cardine.lifecycle.receipts import _load_intent, authority_covers, require_authority
    operation = _operation_path(root, locations.task_id)
    intent = None
    if operation.exists():
        intent = _load_intent(operation)
        if (intent['task_id'] != locations.task_id or intent['root'] != str(root.resolve())
                or intent['base'] != str(inspection['base_commit'])
                or not authority_covers(intent['authority'], require_authority(root), root)):
            raise CardineError('implementation progress has a foreign delivery operation')
        if intent['result'] != 'verified':
            return None  # The dispatcher must reconcile the owned operation first.
    state = _execution_state(root, locations.task_id)
    base = str(inspection['base_commit'])
    enforce_scope(root, state, base, owned=_execution_owned_paths(root, locations.task_id))
    result = verify_delivery(root, state, base, context=locations)
    if result is not None and intent is not None and result['commit'] != intent['commit']:
        raise CardineError('implementation delivery result identity changed')
    return result


@scoped_command
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
    return emit_run(dispatch_run(locations), validate_output)


def run_summary(result):
    text = f"run finished: step {result['step']}, outcome {result['outcome']}"
    if result.get('action') and result['action'] != 'none':
        text += f", action {result['action']}"
    if result.get('stop'):
        text += f", stop {result['stop']['code']}"
    if result.get('next') and result['next'].get('reason'):
        text += f" — {result['next']['reason']}"
    return text



def registration_recovery(locations):
    """Describe the explicit Git step needed before preparing from main."""
    import shlex
    from cardine.shared.git import _run_git
    from cardine.tasks.state import state_path
    from cardine.tasks.status import registration_missing_from_main
    root = locations.primary
    paths = (root / locations.record_path, state_path(root, locations.task_id))
    missing = registration_missing_from_main(root, paths)
    if not missing:
        return None
    all_paths = list(missing)
    branch = _run_git(root, 'branch', '--show-current').stdout.strip()
    staged = all(_run_git(root, 'cat-file', '-e', ':' + path).returncode == 0 for path in all_paths)
    if branch != 'main':
        # Preserve paths that exist only on this branch without overwriting
        # working files left by the switch. Each command remains visible.
        switch = shlex.join(['git', '-C', str(root), 'switch', 'main'])
        restores = []
        for path in missing:
            target = shlex.quote(str(root / path))
            restore = shlex.join(['git', '-C', str(root), 'restore', '--source', branch, '--worktree', '--', path])
            restores.append(f'(test -e {target} || {restore})')
        argv = ['sh', '-c', ' && '.join([switch, *restores])]

    elif not staged:
        argv = ['git', '-C', str(root), 'add', '--', *all_paths]
    else:
        argv = ['git', '-C', str(root), 'commit', '-m', f'Register task {locations.task_id}', '--', *all_paths]
    retry = shlex.join(['cardine', 'run', locations.task_id, '--project', str(root)])
    reason = ('Registration missing from main: ' + ', '.join(missing)
              + '. Stage and commit the missing registration files on main, push when required by the workflow, then retry: ' + retry)
    return envelope(locations.task_id, str(root), step='contract', outcome='next',
                    action='publish-registration', next_command=command_reference(argv, reason),
                    diagnostics=[{'code': 'REGISTRATION_UNCOMMITTED', 'message': reason}])


@scoped_command
def dispatch_run(locations: RunLocations) -> dict:
    """Execute one Stable engine step; console actions share this entry point."""
    from cardine.tasks.state import read_task_state
    from cardine.stops.render import stop_error
    live = LiveLog(locations.common_dir, locations.task_id)
    live.note(f"run {locations.task_id} started")
    stage = "contract"
    try:
        state = read_task_state(locations.primary, locations.task_id, "single",
                                stop_factory=stop_error, require_contract=True)
        if "contract" not in state:
            raise CardineError("missing frozen contract; preview cannot import task prose")
        # RE3b composes measured validation only after a verified delivery.
        # Earlier contract/preparation dispatch and later landing adapters stay
        # independent; editable progress cannot skip those receipt checks.
        from cardine.integration.candidate import operation_path
        if operation_path(locations, 'cleanup').exists():
            result = run_integration_step(locations)
            live.note(run_summary(result))
            return result
        from cardine.lifecycle.control import operation_state
        active = operation_state(locations.worktree, locations.task_id)[0] if locations.worktree.is_dir() else state
        from cardine.lifecycle.control import require_review_budget
        if active['status'] != 'cancelled':
            require_review_budget(locations.worktree, locations.task_id, active)
        if active['status'] == 'queued' and not locations.worktree.is_dir():
            from cardine.tasks.preflight import check_dependencies
            check_dependencies(locations.primary, locations.task_id, '')
            recovery = registration_recovery(locations)
            if recovery is not None:
                live.note(run_summary(recovery))
                return recovery
        stage = "candidate"
        result = (resolve_run(RunFacts(locations.task_id, locations.primary, 'cancelled'))
                  if active['status'] == 'cancelled' else run_integration_step(locations))
        if result is None and active['status'] != 'cancelled':
            stage = "worktree"
            result = _integration_wait(locations) or run_worktree_step(locations, active)
        if result is None and active['status'] != 'cancelled':
            stage = "validation"
            result = _integration_wait(locations) or run_validation_step(locations)
        stage = "contract"
        if result is None:
            result = resolve_run(RunFacts(locations.task_id, locations.primary, state["status"]))
    except CardineStop as error:
        result = _cleanup_wait(locations, error) or diagnostic_result(locations, error, step=stage)
    except Exception as error:
        # An unknown failure carries no ownership proof and must never suggest
        # successful progress or an automatic repair inferred from its prose.
        result = diagnostic_result(locations, stop_error("COMMAND_REFUSED", str(error)), step=stage)
    live.note(run_summary(result))
    return result


def _integration_wait(locations):
    from cardine.integration.candidate import wait_for_lease
    if wait_for_lease(locations):
        return None
    argv = ['cardine', 'run', locations.task_id, '--project', str(locations.primary)]
    return envelope(locations.task_id, str(locations.primary), step='candidate', outcome='waiting',
                    action='wait-for-lease', retry_after_seconds=5,
                    next_command=command_reference(argv, 'Wait for the competing integration'))


def _cleanup_wait(locations, error):
    """A cleanup stop raised while another task integrates is retried after that lease."""
    from cardine.integration.candidate import wait_for_lease
    if error.code != 'CLEANUP_BLOCKED' or not _cleanup_started(locations):
        return None
    try:
        if wait_for_lease(locations, seconds=0):
            return None
    except CardineStop:
        return None
    argv = ['cardine', 'run', locations.task_id, '--project', str(locations.primary)]
    return envelope(locations.task_id, str(locations.primary), step='landing', outcome='waiting',
                    action='wait-for-lease', retry_after_seconds=5,
                    next_command=command_reference(argv, 'Wait for the competing integration'))


def _cleanup_started(locations):
    """Cleanup begins when its intent exists or when the landing is already recorded."""
    from cardine.integration.candidate import operation_path
    from cardine.lifecycle import receipts
    if operation_path(locations, 'cleanup').exists():
        return True
    finalize = operation_path(locations, 'finalize')
    return finalize.exists() and receipts._load_intent(finalize)['result'] is not None


@contextlib.contextmanager
def _inside(project: Path):
    """`worktree prepare` verifies the current directory; `run --project` may start elsewhere."""
    previous = Path.cwd()
    os.chdir(project)
    try:
        yield
    finally:
        os.chdir(previous)


def _start_pending(root: Path, task_id: str) -> bool:
    """True when an intact intent is exactly this step's interrupted start transition."""
    from cardine.lifecycle import receipts
    if not receipts.pending_operation(root, task_id):
        return False
    try:
        intent = receipts._load_intent(receipts._intent_path(root, task_id))
        kind = intent['state']['run']['receipts'][-1]['kind']
        expected = 'transition:' + receipts.digest(receipts.encoded(dict(target='in_progress')))
        return (intent['task_id'] == task_id and intent['state']['status'] == 'in_progress'
                and kind == expected)
    except (CardineError, KeyError, IndexError, TypeError):
        return False


@scoped_command
def run_worktree_step(locations: RunLocations, active: dict) -> dict | None:
    """Perform the contract-to-worktree boundary once; a rerun converges on it.

    Prepare is idempotent over its owned receipt, and execution start replays its
    own interrupted transition, so a killed earlier call needs no special case.
    A task that already left `queued` in its worktree has nothing to do here.
    """
    from cardine.lifecycle import receipts
    from cardine.lifecycle.commands import execution_start
    from cardine.worktree.checkout import prepare_task_worktree
    task_id = locations.task_id
    if (locations.worktree.is_dir() and active['status'] != 'queued'
            and not _start_pending(locations.worktree, task_id)):
        return None
    with _inside(locations.primary):
        if locations.worktree.is_dir() and _start_pending(locations.worktree, task_id):
            worktree = locations.worktree  # Prepared earlier; only the owned start is replayed.
        else:
            worktree = Path(prepare_task_worktree(task_id, locations.root, locations.primary)['worktree'])
            receipts.boundary('after_run_prepare')
    with _inside(worktree):
        started = execution_start(worktree, task_id, context=locations)
        # Commit the state transition Cardine just wrote, so the implementer's
        # own commit leaves a clean worktree (ADR decision 14, rule 3).
        from cardine.shared.git import git_output
        from cardine.tasks.state import state_path
        relative = state_path(worktree, task_id).relative_to(worktree).as_posix()
        if git_output(worktree, 'status', '--porcelain', '--', relative):
            git_output(worktree, 'commit', '-q', '-m', f'Start task {task_id}', '--', relative)
    receipts.boundary('after_run_execution_start')
    argv = ['cardine', 'run', task_id, '--project', str(locations.primary)]
    return envelope(task_id, str(locations.primary), step='worktree', action='execution-start',
                    next_command=command_reference(argv, 'Obtain committed implementation and acceptance evidence'),
                    evidence=[dict(kind='worktree', path=str(worktree),
                                   identity=str(started['commit']))])


@scoped_command
def run_validation_step(locations: RunLocations) -> dict | None:
    """Recover missing task evidence and return the review or C6 boundary."""
    from cardine.lifecycle.validation import byproducts_path, operation_path, run_task_validation
    from cardine.lifecycle.execution import _execution_state
    from cardine.lifecycle.model import WorkRequest
    from cardine.lifecycle import receipts
    root, task_id = locations.worktree, locations.task_id
    if not root.is_dir():
        return None
    state = _execution_state(root, task_id) if not receipts.pending_operation(root, task_id) else None
    if state is not None and state['status'] != 'cancelled':
        from cardine.lifecycle.control import require_review_budget
        require_review_budget(root, task_id, state)
    before_validation = state.get('run', {}).get('validation') if state else None
    contract = state['contract'] if state else {}
    request = WorkRequest('implementer', root,
        receipts.digest(receipts.encoded(contract)),
        tuple(contract.get('expectedCodeSurface', [])), _acceptance_references(contract),
        tuple(contract.get('validation', {}).get('baseline', [])), ('committed implementation delivery',))
    failed_candidate = state.get('run', {}).get('candidateValidation') if state else None
    if failed_candidate and failed_candidate['phase'] == 'failed':
        from cardine.lifecycle.control import source_digest
        from cardine.integration.candidate import require_budget
        require_budget(state, task_id, locations.primary)
        if source_digest(root, task_id) == failed_candidate['binding']['sourceDigest']:
            result = resolve_run(RunFacts(task_id, locations.primary, state['status'],
                contract_ready=True, worktree_ready=True, validation_failed=True, implementation_work=request))
            result['diagnostics'] = [dict(code='CANDIDATE_VALIDATION_FAILED', message=json.dumps(failed_candidate['runs']))]
            return result
    path = operation_path(root, task_id)
    # Only an attempt in progress blocks a new delivery; a finished one stays on disk.
    pending = path.exists() and receipts._load_intent(path).get('phase') not in ('complete', 'invalidated')
    if not pending and implementation_delivery(locations) is None and _committed_implementation(locations, state):
        # A clean, committed change in scope is a delivery the tool can perform
        # itself, so the agent needs no command beyond run (ADR decisions 6 and 14).
        delivered = deliver_run_implementation(locations)
        return envelope(task_id, str(locations.primary), step='implementation', outcome='progress',
                        action='deliver', next_command=command_reference(
                            ['cardine', 'run', task_id, '--project', str(locations.primary)],
                            'Run the complete current validation command set'),
                        evidence=[dict(kind='delivery', path=str(root), identity=str(delivered['commit']))])
    if not pending and implementation_delivery(locations) is None:
        return resolve_run(RunFacts(task_id, locations.primary, 'in_progress',
                           contract_ready=True, worktree_ready=True, implementation_work=request,
                           review_changes_requested=state is not None and state.get('review', {}).get('verdict') == 'CHANGES_REQUESTED'))
    from cardine.shared.errors import CardineStop
    try:
        progress = run_task_validation(root, task_id, context=locations)
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
            tuple(contract.get('expectedCodeSurface', [])), _acceptance_references(contract),
            tuple(contract['validation']['baseline']), ('committed implementation delivery',))
    intent = receipts._load_intent(path) if path.exists() else {}
    byproducts = intent.get('byproducts', []) if intent.get('attemptId') == progress['attemptId'] else []
    def add_byproducts(result):
        if byproducts:
            directory = byproducts_path(root, task_id) / intent['attemptId']
            result['diagnostics'].append(dict(code='VALIDATION_BYPRODUCTS', message=(
                f'moved {len(byproducts)} files that validation created to {directory}: '
                + ', '.join(byproducts[:5]) + '; ignore them in .gitignore or commit them')))
        return result
    passed = progress['phase'] == 'passed'
    from cardine.tasks.validation import host_observations_complete
    if passed and not host_observations_complete(contract, progress):
        result = resolve_run(RunFacts(task_id, locations.primary, state['status'],
            contract_ready=True, worktree_ready=True, validation_failed=True, implementation_work=request))
        result['diagnostics'] = [dict(code='ACCEPTANCE_UNMET',
            message='An enforced host profile needs a matching declared validation command and passing observation')]
        return add_byproducts(result)
    from cardine.review.progress import review_progress, prepare_review
    from cardine.lifecycle.control import require_review_budget
    require_review_budget(root, task_id, state)
    approved, review_pending = review_progress(root, task_id, state)
    if passed and state['contract']['options']['review'] == 'required' and not approved:
        state = prepare_review(root, task_id, context=locations)
    facts = RunFacts(task_id, locations.primary, state['status'],
        review_approved=approved, review_pending=review_pending,
        contract_ready=True, worktree_ready=True, implementation_delivered=True,
        validation_passed=passed, validation_failed=not passed,
        implementation_work=request,
        review_work=WorkRequest('reviewer', root, request.snapshot_digest,
            request.expected_surface, request.acceptance_references,
            request.validation_references, ('independent source-bound review',)),
        review_required=state['contract']['options']['review'] == 'required')
    result = resolve_run(facts)
    if result['step'] == 'candidate':
        if before_validation != progress:
            result['action'] = 'C6'
            result['evidence'] = [dict(kind='task-validation', path=progress['evidence'], identity=progress['attemptId'])]
            return add_byproducts(result)
        gated = run_ci_step(locations, facts, request, state)
        if gated is not None:
            return add_byproducts(gated)
        return add_byproducts(run_integration_step(locations, prepare=True))
    result['action'] = 'task-validation'
    result['evidence'] = [dict(kind='task-validation', path=progress['evidence'], identity=progress['attemptId'])]
    if not passed:
        result['diagnostics'] = [dict(code='VALIDATION_FAILED', message=json.dumps(progress['runs']))]
    return add_byproducts(result)


@scoped_command
def run_ci_step(locations: RunLocations, facts: RunFacts, request, state: dict) -> dict | None:
    """Gate the direct candidate on CI for the delivered head when the contract requires it."""
    from dataclasses import replace
    from cardine.integration import ci
    if ci.ci_policy(state['contract']) is None:
        return None
    outcome = ci.ci_gate(locations)
    if outcome is None or (outcome['phase'] == 'passed' and not outcome['changed']):
        return None
    task_id, argv = locations.task_id, ['cardine', 'run', locations.task_id, '--project', str(locations.primary)]
    evidence = [dict(kind='ci', path=f"{outcome['repository']} {outcome['ref']}", identity=outcome['head'])]
    if outcome['phase'] == 'failed':
        return envelope(task_id, str(locations.primary), step='implementation', outcome='iterate', action='ci-failed',
            work=request.as_json(), evidence=evidence, diagnostics=[dict(code='VALIDATION_FAILED', message=outcome['detail'])],
            next_command=command_reference(argv, 'Repair the task implementation'))
    if outcome['phase'] == 'waiting':
        result = resolve_run(replace(facts, ci_pending=True))
        result['diagnostics'] = [dict(code='CI_PENDING', message=outcome['detail'])]
    else:
        result = resolve_run(facts)
    result['action'] = 'poll-ci' if outcome['phase'] == 'waiting' else 'ci-passed'
    result['evidence'] = evidence
    return result


def diagnostic_result(locations: RunLocations, error, *, step: str = "contract") -> dict:
    """Adapt a cause-classified error, preserving its exact recovery command."""
    from cardine.stops.render import outcome_for_code
    from cardine.stops.render import stop_error
    if error.code not in load_stop_registry() or error.detail is None or error.resume is None:
        error = stop_error("COMMAND_REFUSED", "unknown or untyped diagnostic: " + error.code)
    detail = error.detail
    if error.code == "SCOPE_CHANGE_REQUIRED" and error.scope_paths and error.scope_record:
        update = shlex.join(["cardine", "task", "contract", "update", locations.task_id,
                             "--project", str(locations.worktree)])
        record = str(locations.worktree / error.scope_record)
        detail += (f". Approval is requested to expand task {locations.task_id}'s frozen Expected code surface "
                   f"to include these paths. If approved, add only the approved paths to {shlex.quote(record)} "
                   f"in the task worktree, update Validation if another check is required, then run: {update}. "
                   "If declined, restore the changes to the approved surface before retrying")
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


@scoped_command
def run_integration_step(locations: RunLocations, *, prepare=False) -> dict | None:
    """One bounded candidate, finalize or verified delivery step."""
    from cardine.integration.candidate import (operation_path, wait_for_lease,
        require_budget)
    from cardine.integration.landing import landing_for
    from cardine.integration.finalize import finalization_aborted
    from cardine.lifecycle.control import operation_state
    from cardine.tasks.identity import resolve_task_identity
    from cardine.worktree.storage import _lifecycle_paths
    root, task_id = locations.primary, locations.task_id
    cleanup = operation_path(locations, 'cleanup')
    if cleanup.exists():
        from cardine.integration.cleanup import finish_delivery
        result = finish_delivery(locations)
        return envelope(task_id, str(root), step='landing', action='cleanup', outcome='done',
                        evidence=[dict(kind='landing', path=str(cleanup), identity=result['merge_commit'])])
    if not locations.worktree.is_dir():
        return None
    state, _ = operation_state(locations.worktree, task_id)
    strategy = landing_for(state['contract']['options']['landingMode'])
    identity = resolve_task_identity(root, task_id, 'existing')
    _, lease, staged = _lifecycle_paths(root, identity)
    final = operation_path(locations, 'finalize')
    argv = ['cardine', 'run', task_id, '--project', str(root)]
    if final.exists() and not finalization_aborted(locations):
        landed = strategy.finish_delivery(locations)
        return envelope(task_id, str(root), step='landing', action='cleanup', outcome='done',
            evidence=[dict(kind='landing', path=str(final), identity=landed['merge_commit'])])
    if not staged.exists() and not prepare:
        return None
    if not wait_for_lease(locations):
        return envelope(task_id, str(root), step='candidate', outcome='waiting',
            action='wait-for-lease', retry_after_seconds=5,
            next_command=command_reference(argv, 'Wait for the competing integration'))
    if not staged.exists():
        if not prepare:
            return None
        try:
            strategy.prepare_candidate(task_id, None, root)
        except CardineStop as error:
            if error.code != 'LEASE_HELD' or (lease.exists() and wait_for_lease(locations, seconds=0)):
                raise
            return envelope(task_id, str(root), step='candidate', outcome='waiting',
                action='wait-for-lease', retry_after_seconds=5,
                next_command=command_reference(argv, 'Wait for the competing integration'))
    from cardine.integration.candidate import verified_candidate
    try:
        measured = verified_candidate(locations)
    except CardineStop as error:
        if error.code != 'EVIDENCE_MISMATCH':
            raise
        return _reverse_stale_candidate(strategy, locations, error)
    if measured and measured['phase'] == 'passed':
        landed = strategy.finalize_landing(task_id, None, root)
        return envelope(task_id, str(root), step='landing', action='finalize',
            next_command=command_reference(argv, 'Push and clean up the landed task'))
    try:
        progress = strategy.validate_candidate(task_id, root)
    except CardineStop as error:
        if error.code == 'EVIDENCE_MISMATCH' and error.detail == 'task source moved after staging':
            return _reverse_stale_candidate(strategy, locations, error)
        if error.code in ('VALIDATION_RETRY_LIMIT', 'EVIDENCE_MISMATCH'):
            strategy.reconcile_landing(task_id, root)
        raise
    if progress['phase'] == 'passed':
        return _candidate_finalize_next(locations)
    strategy.reconcile_landing(task_id, root)
    state, _ = operation_state(locations.worktree, task_id)
    require_budget(state, task_id, root)
    from cardine.lifecycle.model import WorkRequest
    from cardine.lifecycle import receipts
    contract = state['contract']
    request = WorkRequest('implementer', locations.worktree, receipts.digest(receipts.encoded(contract)),
        tuple(contract['expectedCodeSurface']), _acceptance_references(contract),
        tuple(contract['validation']['baseline']), ('repair candidate validation failure',))
    return envelope(task_id, str(root), step='implementation', outcome='iterate',
        action='abort-failed-candidate', work=request.as_json(),
        diagnostics=[dict(code='CANDIDATE_VALIDATION_FAILED', message=json.dumps(progress['runs']))],
        next_command=command_reference(argv, 'Repair the task implementation'))


def _reverse_stale_candidate(strategy, locations, error):
    """Reverse the task's own stale candidate with the engine's owned abort; the run goes on to delivery.

    A candidate the engine cannot prove safe to reverse is an integrity stop that names both refusals.
    """
    from cardine.stops.render import refusal, stop_error
    try:
        strategy.reconcile_landing(locations.task_id, locations.primary)
    except CardineError as refused:
        raise stop_error('INTEGRITY_MISMATCH', refusal(
            'stale candidate not reversed', 'an owned candidate the engine can abort',
            f'staging refused: {error.detail}', f'abort refused: {refused}',
            'resolve the difference named above, then rerun'),
            task_id=locations.task_id, project=locations.primary) from refused
    # The abort receipt edits the task state in the worktree; commit exactly that file, as the
    # worktree step does for its own transitions, so the moved branch is clean to deliver again.
    from cardine.shared.git import git_output
    from cardine.tasks.state import state_path
    relative = state_path(locations.worktree, locations.task_id).relative_to(locations.worktree).as_posix()
    if git_output(locations.worktree, 'status', '--porcelain', '--', relative):
        git_output(locations.worktree, 'commit', '-q', '-m', f'Reverse stale candidate {locations.task_id}', '--', relative)
    return None


def _candidate_finalize_next(locations):
    # Finalize on the next bounded invocation; its durable intent is created there.
    return envelope(locations.task_id, str(locations.primary), step='candidate',
        action='validate-candidate', next_command=command_reference(
            ['cardine', 'run', locations.task_id, '--project', str(locations.primary)],
            'Finalize the measured candidate'))


def _acceptance_references(contract):
    """Spike deliverables, or the record's criteria for a standard task."""
    return tuple(contract.get('deliverables') or ()) or (contract['recordPath'] + '#acceptance-criteria',)


def _committed_implementation(locations, state):
    """A clean worktree whose commits since its base change a path Cardine does not own."""
    from cardine.lifecycle.execution import _execution_location, _execution_owned_paths
    from cardine.shared.git import git_output
    root = locations.worktree
    if state is None or state['status'] != 'in_progress':
        return False
    if git_output(root, 'status', '--porcelain'):
        from cardine.lifecycle.source import commit_own_records
        commit_own_records(root, locations.task_id, context=locations)
        if git_output(root, 'status', '--porcelain'):
            return False
    base = str(_execution_location(root, locations.task_id, context=locations)['base_commit'])
    owned = _execution_owned_paths(root, locations.task_id, context=locations)
    changed = set(git_output(root, 'diff', '--name-only', base, 'HEAD').splitlines())
    review = state.get('review', {})
    if review.get('verdict') == 'CHANGES_REQUESTED':
        # The rejected commit is not a new delivery; only a later change to the work is.
        repaired = set(git_output(root, 'diff', '--name-only', review['reviewed_commit'], 'HEAD').splitlines())
        if not repaired - owned:
            return False
    return bool(changed - owned)
