"""Command parsing and dispatch for Cardine."""

from __future__ import annotations

from cardine.shared.layout import names

from pathlib import Path
import argparse
import json
import os
import shlex
import sys

from cardine.hosts.codex import apply_codex_configuration, plan_codex_configuration, print_codex_configuration_plan
from cardine.hosts.setup import apply_setup, codex_doctor, plan_setup, print_setup_plan
from cardine.integration.evidence import check_validation_evidence, record_task_evidence
from cardine.integration.merge import abort_task_integration, cleanup_task_worktree, finalize_task_integration, stage_task_integration
from cardine.lifecycle.closure import advance_task_closure
from cardine.lifecycle.commands import execution_deliver, execution_start
from cardine.lifecycle.execution import delivery_readiness
from cardine.release.update import run_self_check, run_self_update
from cardine.release.version import parse_semver, read_raw_version
from cardine.review.verdict import record_review_verdict
from cardine.shared.authority import adr_list, adr_show, context_authority
from cardine.shared.constants import USAGE_HOSTS
from cardine.shared.context import context_size_report, format_context_size_report
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.git import canonical_project_root
from cardine.shared.journal import LifecycleJournalEntry
from cardine.shared.paths import SCRIPTS_ROOT
from cardine.shared.project import read_project_declaration
from cardine.shared.usage import format_usage_report, usage_report
from cardine.stops.registry import load_stop_registry
from cardine.stops.render import format_stop, stop_error
from cardine.tasks.contract import check_handoff, default_handoff_path
from cardine.tasks.identity import next_milestone_task_identity, resolve_project_locations, resolve_task_identity, task_identity_json
from cardine.tasks.importer import import_task_states
from cardine.tasks.preflight import execution_contract, execution_preflight, readiness_check, reconcile_execution_contract
from cardine.tasks.recording import run_validation
from cardine.tasks.state import state_path
from cardine.tasks.transitions import close_task, transition_task_state
from cardine.templates.audit import retired_text_advisories, run_audit
from cardine.templates.catalog import manifest_workflow_mode
from cardine.templates.files import manifest_baseline_version
from cardine.templates.merge import lock_project, plan_from_baseline
from cardine.templates.mode import detect_mode
from cardine.templates.upgrade import apply_upgrade
from cardine.templates.upgrade_support import plan_has_blockers, prepare_upgrade_targets, print_plan
from cardine.worktree.checkout import active_worktree_task, inspect_task_worktree, prepare_task_worktree, registered_worktree_task_states, repair_task_worktree_base
from cardine.worktree.closure_status import closure_status
from cardine.worktree.paths import _task_worktree_path_for_identity, handoff_worktree_value, task_worktree_path, validate_worktree_collision
from cardine.worktree.storage import _effective_worktree_root, _verified_lifecycle_project, resolve_worktree_root

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

class CardineArgumentParser(argparse.ArgumentParser):
    """Use sysexits-style usage status for machine-oriented namespaces."""

    def error(self, message: str) -> None:
        if " task identity" in self.prog or " worktree" in self.prog:
            self.print_usage(sys.stderr)
            self.exit(64, f"{self.prog}: error: {message}\n")
        super().error(message)


class ShowVersionAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(parse_semver(read_raw_version(namespace.framework_root)))
        parser.exit()


def main() -> int:
    if sys.argv[1:2] == ["hook"]:
        try:
            Path.cwd()
        except FileNotFoundError:
            # Advisory hooks must also tolerate an inherited, deleted cwd.
            return 0
    journal = LifecycleJournalEntry()
    exit_code = _run_cli(journal)
    journal.write(exit_code)
    return exit_code


def build_parser() -> CardineArgumentParser:
    """Build the CLI parser, also used to verify the published command surface."""
    parser = CardineArgumentParser(prog="cardine")
    parser.add_argument(
        "--framework-root",
        type=Path,
        default=Path(os.environ.get("CARDINE_ROOT", SCRIPTS_ROOT.parent)),
    )
    parser.add_argument(
        "--version",
        action=ShowVersionAction,
        help="print the framework SemVer, including prerelease and build metadata",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    self_check = subparsers.add_parser(
        "self-check", help="inspect this Cardine installation"
    )
    self_check.add_argument(
        "--check-latest",
        action="store_true",
        required=True,
        help="query the latest public GitHub Release",
    )

    self_update = subparsers.add_parser(
        "self-update", help="update the CLI checkout (experimental)",
        description="Experimental: plan or apply an update of the running CLI checkout.",
    )
    update_mode = self_update.add_mutually_exclusive_group(required=True)
    update_mode.add_argument("--check", action="store_true")
    update_mode.add_argument("--apply", action="store_true")
    self_update.add_argument("--to", dest="target_tag")

    console = subparsers.add_parser(
        "console", help="open the read-only project state console (experimental)",
        description="Experimental: interactive keys and agent launch may change in minor releases."
    )
    console.add_argument("--project", type=Path, default=Path.cwd())
    console.add_argument(
        "--interval", type=float, default=2.0,
        help="seconds between local refreshes (default: 2)",
    )

    lock = subparsers.add_parser("lock", help="register a newly initialized project for deterministic upgrades")
    lock.add_argument("--project", type=Path, default=Path.cwd())
    lock.add_argument("--mode", choices=("single",), default="single")

    upgrade = subparsers.add_parser("upgrade", help="plan or apply a framework upgrade")
    upgrade.add_argument("--project", type=Path, default=Path.cwd())
    group = upgrade.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    upgrade.add_argument(
        "--owner-reconciled",
        action="store_true",
        help="register the target version and baseline without touching any managed file, "
        "for a project too customized for the automatic three-way merge whose developer has "
        "already reconciled every managed file by hand outside this command; --apply only",
    )
    upgrade.add_argument(
        "--stop-before-retirement",
        action="store_true",
        help="cap this upgrade to the last migration before the first one that retires a "
        "duplicated entry-point marker, so a long-lag consumer can complete an additive-only "
        "release; a no-op if no pending migration retires anything",
    )

    audit = subparsers.add_parser(
        "audit",
        help="verify protected capability-marker regions were not edited outside cardine upgrade",
    )
    audit.add_argument("--project", type=Path, default=Path.cwd())
    audit.add_argument(
        "--mode",
        choices=("single",),
        help="single distribution; validates project configuration when omitted",
    )
    audit.add_argument(
        "--ci-profile",
        help="gate catalog-required static installation while retaining visible host UNVERIFIED rows",
    )

    status = subparsers.add_parser("status", help="show read-only task status from validated states")
    status.add_argument("--project", type=Path, default=Path.cwd())
    status.add_argument("--all", action="store_true")
    status.add_argument("--write", action="store_true", help="atomically regenerate the configured queue and the plan's generated status region")
    status.add_argument("--format", choices=("text", "json"), default="text")

    locations = subparsers.add_parser("locations", help="print resolved project locations")
    locations.add_argument("--project", type=Path, default=Path.cwd())
    locations.add_argument("--field", choices=("queue", "queue-archive", "task-roots", "review-root", "handoff-root", "adr-log", "plan"))

    project = subparsers.add_parser("project", help="show the resolved project declaration")
    project.add_argument("show", nargs="?", default="show")
    project.add_argument("--project", type=Path, default=Path.cwd())
    project.add_argument("--field", choices=("project", "locations", "validation-scoping", "ci", "reviewer-author"))
    project.add_argument("--format", choices=("json", "text"), default="text")

    setup = subparsers.add_parser("setup", help="plan or apply worktree, Codex, and project Claude Code setup")
    setup_group = setup.add_mutually_exclusive_group(required=True)
    setup_group.add_argument("--check", action="store_true")
    setup_group.add_argument("--apply", action="store_true")
    setup.add_argument("--worktree-root", type=Path)
    setup.add_argument("--project", type=Path, default=Path.cwd())
    setup.add_argument(
        "--task-identity",
        choices=("opaque", "milestone"),
        help="record the project's task-identity choice without changing an existing declaration",
    )
    setup.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)

    codex = subparsers.add_parser("codex", help="configure and diagnose Codex task-worktree access")
    codex_sub = codex.add_subparsers(dest="codex_command", required=True)
    codex_configure = codex_sub.add_parser("configure", help="plan or apply a bounded Codex permission profile")
    codex_configure_group = codex_configure.add_mutually_exclusive_group(required=True)
    codex_configure_group.add_argument("--check", action="store_true")
    codex_configure_group.add_argument("--apply", action="store_true")
    codex_configure.add_argument("--worktree-root", type=Path)
    codex_configure.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)
    codex_configure.add_argument("--requirements", type=Path, help=argparse.SUPPRESS)
    codex_path = codex_sub.add_parser("worktree-path", help="derive one repository-qualified task worktree path")
    codex_path.add_argument("task_id")
    codex_path.add_argument("--project", type=Path, default=Path.cwd())
    codex_path.add_argument("--worktree-root", type=Path)
    codex_doctor_parser = codex_sub.add_parser("doctor", help="report Codex host capabilities separately")
    codex_doctor_parser.add_argument("--project", type=Path, default=Path.cwd())
    codex_doctor_parser.add_argument("--worktree-root", type=Path)
    codex_doctor_parser.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)

    worktree = subparsers.add_parser("worktree", help="run the bounded host-neutral task-worktree lifecycle")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)
    worktree_path_parser = worktree_sub.add_parser("path", help="derive the canonical task-worktree path")
    worktree_path_parser.add_argument("task_id")
    worktree_path_parser.add_argument("--project", type=Path)
    worktree_path_parser.add_argument("--worktree-root", type=Path)
    worktree_path_parser.add_argument("--format", choices=("json",))
    worktree_prepare = worktree_sub.add_parser("prepare", help="create or select exactly one canonical task worktree")
    worktree_prepare.add_argument("task_id")
    worktree_prepare.add_argument("--project", type=Path)
    worktree_prepare.add_argument("--worktree-root", type=Path)
    worktree_prepare.add_argument("--base", choices=("main",), default="main")
    worktree_prepare.add_argument(
        "--resume",
        action="store_true",
        help="accept an existing dirty worktree of this task; never creates or changes anything",
    )
    worktree_prepare.add_argument("--format", choices=("json",), required=True)
    worktree_check = worktree_sub.add_parser("check", help="inspect the effective worker worktree without mutation")
    worktree_check.add_argument("task_id")
    worktree_check.add_argument("--resume", action="store_true", help="accept only dirty-worktree after explicit Resume")
    worktree_check.add_argument("--project", type=Path)
    worktree_check.add_argument("--worktree-root", type=Path)
    worktree_check.add_argument("--format", choices=("json",), required=True)
    worktree_repair = worktree_sub.add_parser("repair-base", help="repair a proven commit-less main fast-forward base")
    worktree_repair.add_argument("task_id")
    worktree_repair.add_argument("--project", type=Path)
    worktree_repair.add_argument("--worktree-root", type=Path)
    worktree_repair.add_argument("--format", choices=("json",), required=True)
    worktree_active = worktree_sub.add_parser("active", description="Framework-internal: no compatibility promise.", help="resolve the active task from this registered worktree (framework-internal)")
    worktree_active.add_argument("--format", choices=("json",), required=True)
    worktree_states = worktree_sub.add_parser("states", description="Framework-internal: no compatibility promise.", help="list task states from registered worktrees (framework-internal)")
    worktree_states.add_argument("--project", type=Path, default=Path.cwd())
    worktree_states.add_argument("--format", choices=("json",), required=True)
    worktree_evidence = worktree_sub.add_parser(
        "evidence", description="Framework-internal: no compatibility promise.", help="record Git-derived task validation evidence without running commands (framework-internal)"
    )
    worktree_evidence.add_argument("task_id")
    worktree_evidence.add_argument("--project", type=Path)
    worktree_evidence.add_argument("--worktree-root", type=Path)
    worktree_evidence.add_argument("--accepted", action="store_true")
    worktree_evidence.add_argument("--validation-command", action="append", default=[])
    worktree_evidence.add_argument("--validation-exit-code", action="append", type=int, default=[])
    worktree_evidence.add_argument("--task-dependency", action="append", default=[])
    worktree_evidence.add_argument("--task-behavioral-surface", action="append", default=[])
    worktree_evidence.add_argument("--main-advanced-dependency", action="append", default=[])
    worktree_evidence.add_argument("--main-advanced-behavioral-surface", action="append", default=[])
    worktree_evidence.add_argument("--full-validation-required", action="store_true")
    worktree_evidence.add_argument("--format", choices=("json",), required=True)
    worktree_closure_status = worktree_sub.add_parser(
        "closure-status", description="Framework-internal: no compatibility promise.", help="report the next closure step without changing lifecycle state (framework-internal)"
    )
    worktree_closure_status.add_argument("task_id")
    worktree_closure_status.add_argument("--project", type=Path)
    worktree_closure_status.add_argument("--worktree-root", type=Path)
    worktree_closure_status.add_argument("--format", choices=("json",))
    worktree_advance = worktree_sub.add_parser(
        "advance", help="run the mechanical closure steps and report the next action the agent owns"
    )
    worktree_advance.add_argument("task_id")
    worktree_advance.add_argument("--project", type=Path)
    worktree_advance.add_argument("--worktree-root", type=Path)
    worktree_advance.add_argument("--accepted", action="store_true")
    worktree_advance.add_argument("--validation-command", action="append", default=[])
    worktree_advance.add_argument("--validation-exit-code", action="append", type=int, default=[])
    worktree_advance.add_argument("--candidate-command", action="append", default=[])
    worktree_advance.add_argument("--candidate-exit-code", action="append", type=int, default=[])
    worktree_advance.add_argument("--format", choices=("json",), required=True)
    worktree_integrate = worktree_sub.add_parser("integrate", help="stage, finalize, or abort one owned integration")
    integrate_sub = worktree_integrate.add_subparsers(dest="integrate_command", required=True)
    integrate_stage = integrate_sub.add_parser("stage", help="lease and stage the prescribed no-commit merge")
    integrate_stage.add_argument("task_id")
    integrate_stage.add_argument("--project", type=Path)
    integrate_stage.add_argument("--worktree-root", type=Path)
    integrate_stage.add_argument("--evidence", type=Path, required=True)
    integrate_stage.add_argument("--format", choices=("json",), required=True)
    integrate_finalize = integrate_sub.add_parser("finalize", help="commit an exactly validated staged candidate")
    integrate_finalize.add_argument("task_id")
    integrate_finalize.add_argument("--project", type=Path)
    integrate_finalize.add_argument("--evidence", type=Path, required=True)
    integrate_finalize.add_argument("--format", choices=("json",), required=True)
    integrate_abort = integrate_sub.add_parser("abort", help="abort one Cardine-owned staged integration")
    integrate_abort.add_argument("task_id")
    integrate_abort.add_argument("--project", type=Path)
    integrate_abort.add_argument("--format", choices=("json",), required=True)
    worktree_cleanup = worktree_sub.add_parser("cleanup", help="remove an integrated worktree and its merged local branch")
    worktree_cleanup.add_argument("task_id")
    worktree_cleanup.add_argument("--project", type=Path)
    worktree_cleanup.add_argument("--worktree-root", type=Path)
    worktree_cleanup.add_argument("--format", choices=("json",), required=True)

    validation = subparsers.add_parser("validation", description="Framework-internal: no compatibility promise.", help="read and verify an external validation evidence record (framework-internal)")
    validation_sub = validation.add_subparsers(dest="validation_command", required=True)
    validation_check = validation_sub.add_parser("check", description="Framework-internal: no compatibility promise.", help="verify a record without running validation (framework-internal)")
    validation_check.add_argument("record", type=Path)
    validation_check.add_argument("--project", type=Path, default=Path.cwd())
    validation_check.add_argument("--commit")
    validation_check.add_argument("--format", choices=("json",), required=True)

    review = subparsers.add_parser("review", help="record commit-bound task reviews")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    verdict = review_sub.add_parser("verdict", help="record a verdict and its task-state transition")
    verdict.add_argument("task_id")
    verdict.add_argument("verdict", choices=("APPROVE", "CHANGES_REQUESTED", "BLOCKED"))
    verdict.add_argument("--owner", action="store_true")
    verdict.add_argument("--body", default="", help="free-form review Markdown")
    verdict.add_argument("--project", type=Path, default=Path.cwd())
    verdict.add_argument("--format", choices=("json",), default="json")

    task = subparsers.add_parser("task", help="inspect task records and identities")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    new = task_sub.add_parser("new", help="atomically create a task record and queued state")
    new.add_argument("task_id")
    new.add_argument("--record", type=Path, required=True, help="complete proposed UTF-8 record")
    new.add_argument("--quick", action="store_true", help="use the minimal quick-task contract")
    new.add_argument("--recover", action="store_true", help="safely recover the journaled interrupted pair")
    new.add_argument("--project", type=Path, default=Path.cwd())
    new.add_argument("--format", choices=("json",), default="json")
    contract_task = task_sub.add_parser("contract", help="explicitly revise a frozen task contract")
    contract_sub = contract_task.add_subparsers(dest="task_contract_command", required=True)
    contract_update = contract_sub.add_parser("update", help="revalidate the record and atomically update its snapshot and history")
    contract_update.add_argument("task_id")
    contract_update.add_argument("--project", type=Path, default=Path.cwd())
    contract_update.add_argument("--format", choices=("json",), default="json")
    transition = task_sub.add_parser("transition", help="apply a tracked task-state transition")
    transition.add_argument("task_id")
    transition.add_argument("status")
    transition.add_argument("--cancellation-authority", default="")
    transition.add_argument("--reason", default="")
    transition.add_argument("--project", type=Path, default=Path.cwd())
    transition.add_argument("--format", choices=("json",), default="json")
    outcome = task_sub.add_parser("outcome", help="record a spike result without closing the task")
    outcome.add_argument("task_id")
    outcome.add_argument("outcome", choices=("ANSWERED", "INCONCLUSIVE"))
    outcome.add_argument("--project", type=Path, default=Path.cwd())
    outcome.add_argument("--format", choices=("json",), default="json")
    close = task_sub.add_parser("close", help="verify closure from committed records; the record stays at its path")
    close.add_argument("task_id")
    close.add_argument("--project", type=Path, default=Path.cwd())
    close.add_argument("--format", choices=("json",), default="json")
    state = task_sub.add_parser("state", help="explicit task-state adoption")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    state_import = state_sub.add_parser("import", help="preview or create state for legacy tasks")
    state_import.add_argument("task_ids", nargs="*")
    state_import.add_argument("--apply", action="store_true")
    state_import.add_argument("--include-terminal", action="store_true",
                              help="also propose state for terminal tasks")
    state_import.add_argument("--project", type=Path, default=Path.cwd())
    state_import.add_argument("--format", choices=("json",), default="json")
    identity = task_sub.add_parser("identity", help="resolve the project-selected task identity policy")
    identity_sub = identity.add_subparsers(dest="identity_command", required=True)
    identity_check = identity_sub.add_parser("check", description="Framework-internal: no compatibility promise.", help="validate and print one resolved task identity (framework-internal)")
    identity_check.add_argument("task_id")
    identity_check.add_argument("--project", type=Path, default=Path.cwd())
    identity_check.add_argument("--format", choices=("json",), required=True)
    identity_next = identity_sub.add_parser("next", help="derive the next milestone-mode task identity")
    identity_next.add_argument("--milestone", required=True)
    identity_next.add_argument("--workstream", required=True)
    identity_next.add_argument("--project", type=Path, default=Path.cwd())
    identity_next.add_argument("--format", choices=("json",), required=True)

    adr = subparsers.add_parser("adr", help="read a project's ADR log")
    adr_sub = adr.add_subparsers(dest="adr_command", required=True)
    adr_show_parser = adr_sub.add_parser("show", help="print exactly one ADR section")
    adr_show_parser.add_argument("adr_id")
    adr_show_parser.add_argument("--project", type=Path, default=Path.cwd())
    adr_list_parser = adr_sub.add_parser("list", help="print one line per ADR: ID, title, and status")
    adr_list_parser.add_argument("--project", type=Path, default=Path.cwd())
    adr_list_parser.add_argument("--status", help="keep only entries whose Status field equals this value, ignoring case")
    adr_list_parser.add_argument("--format", choices=("text", "json"), default="text")

    context = subparsers.add_parser("context", help="inspect task authority or measure a role's startup read set")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_authority_parser = context_sub.add_parser(
        "authority", help="print a task's Authority entries resolved to ADR/spec excerpts"
    )
    context_authority_parser.add_argument("task_id")
    context_authority_parser.add_argument("--project", type=Path, default=Path.cwd())
    context_authority_parser.add_argument(
        "--labels-only", action="store_true", help="print source + heading only, not excerpt bodies"
    )
    context_size_parser = context_sub.add_parser("size", help="measure the documents a workflow role is instructed to read")
    context_size_parser.add_argument("--role", required=True, help="workflow role (for example implementation or review)")
    context_size_parser.add_argument("--task", dest="context_task_id")
    context_size_parser.add_argument("--project", type=Path, default=Path.cwd())
    context_size_parser.add_argument("--threshold-bytes", type=int, default=None, help="fail when an included file exceeds this size")
    context_size_parser.add_argument("--format", choices=("json", "text"), default="text")

    usage = subparsers.add_parser("usage", help="report local host session token counters (experimental)", description="Experimental: report local host session token counters without reading message content.")
    usage_sub = usage.add_subparsers(dest="usage_command", required=True)
    usage_report_parser = usage_sub.add_parser("report", help="summarize private host session token counters (experimental)", description="Experimental: summarize private host session token counters.")
    usage_report_parser.add_argument("--host", choices=USAGE_HOSTS)
    usage_report_parser.add_argument("--project", type=Path)
    usage_report_parser.add_argument("--since", help="include sessions starting on or after YYYY-MM-DD")
    usage_report_parser.add_argument("--breakdown", action="store_true", help="report the call with the greatest input growth")
    usage_report_parser.add_argument("--format", choices=("json", "text"), default="text")

    execution = subparsers.add_parser("execution", help="validate a governed task's durable execution evidence")
    execution_sub = execution.add_subparsers(dest="execution_command", required=True)
    for operation in ("start", "deliver"):
        boundary = execution_sub.add_parser(operation, help=f"verified execution {operation} boundary")
        boundary.add_argument("task_id")
        boundary.add_argument("--project", type=Path, default=Path.cwd())
        boundary.add_argument("--format", choices=("json",), default="json")
        if operation == "start":
            boundary.add_argument("--resume", action="store_true", help="only after explicit Resume and dirty-diff inspection")
    preflight = execution_sub.add_parser("preflight", help="check the task contract before implementation")
    preflight.add_argument("task_id")
    preflight.add_argument("--project", type=Path, default=Path.cwd())
    contract = execution_sub.add_parser("contract", help="print the profile-resolved execution contract for a task")
    contract.add_argument("task_id")
    contract.add_argument("--project", type=Path, default=Path.cwd())
    reconcile = execution_sub.add_parser(
        "reconcile", help="refresh a nonterminal task's generated execution contract"
    )
    reconcile.add_argument("task_id")
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--project", type=Path, default=Path.cwd())
    handoff = execution_sub.add_parser("handoff-check", help="check a structured completion handoff")
    handoff.add_argument("task_id")
    handoff.add_argument("report", type=Path, nargs="?")
    handoff.add_argument("--project", type=Path, default=Path.cwd())
    ready = execution_sub.add_parser("ready-check", help="require preflight and complete handoff before review")
    ready.add_argument("task_id")
    ready.add_argument("report", type=Path, nargs="?")
    ready.add_argument("--project", type=Path, default=Path.cwd())
    validate = execution_sub.add_parser("validate", help="run one task-declared literal validation command")
    validate.add_argument("task_id")
    validate.add_argument("validation_id")
    validate.add_argument("--project", type=Path, default=Path.cwd())

    hook = subparsers.add_parser("hook", help="run a Cardine host hook entry point")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    read_guard = hook_sub.add_parser("read-guard", help="apply the advisory-safe read guard")
    read_guard.add_argument("--host", choices=("codex",), required=True)
    stop_audit = hook_sub.add_parser("stop-audit", help="record `BLOCKED <CODE>` reports that no command emitted (Stop hook)")
    stop_audit.add_argument("--host", choices=("claude", "codex"), default="claude")

    return parser


def _run_cli(journal: LifecycleJournalEntry) -> int:
    arguments = build_parser().parse_args()
    journal.begin(arguments)
    framework_root = arguments.framework_root.resolve()
    project_root = (
        arguments.project.resolve()
        if hasattr(arguments, "project") and arguments.project is not None
        else None
    )
    try:
        if arguments.command == "self-update":
            # Environment and --framework-root select upgrade inputs, never the
            # checkout that owns this running executable.
            return run_self_update(SCRIPTS_ROOT.parent,
                                   apply=arguments.apply, target_tag=arguments.target_tag)
        if arguments.command == "self-check":
            return run_self_check(framework_root)
        if arguments.command == "console":
            if not 0.2 <= arguments.interval <= 60:
                raise CardineError("--interval must be between 0.2 and 60")
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise CardineError("interactive console requires a terminal")
            console_path = framework_root / "scripts" / "project_console.py"
            if not console_path.is_file():
                raise CardineError(f"console is unavailable from framework root: {framework_root}")
            sys.path.insert(0, str(console_path.parent))
            from cardine.console import entry as project_console

            return project_console.main([
                "--project", str(project_root), "--interval", str(arguments.interval),
            ])
        if arguments.command == "lock":
            lock_project(project_root, framework_root, arguments.mode)
        elif arguments.command == "audit":
            mode = arguments.mode or detect_mode(project_root)
            return run_audit(project_root, framework_root, mode, arguments.ci_profile)
        elif arguments.command == "status":
            from cardine.tasks.status import load_task_status, render_task_status
            if arguments.write:
                from cardine.tasks.status_render import write_views
                written = write_views(project_root)
                print("\n".join(f"updated {path.relative_to(project_root.resolve())}" for path in written) or "views already up to date")
                return 0
            report = load_task_status(project_root, all_tasks=arguments.all)
            print(json.dumps(report, sort_keys=True) if arguments.format == "json" else render_task_status(report))
            return 2 if report["diagnostics"] else 0
        elif arguments.command == "locations":
            locations = resolve_project_locations(project_root)
            if arguments.field == "queue":
                print(locations.queue)
            elif arguments.field == "queue-archive":
                print(locations.queue.with_name("QUEUE_ARCHIVE.md"))
            elif arguments.field == "task-roots":
                print("\n".join(str(root) for root in locations.task_roots))
            elif arguments.field == "review-root":
                print(locations.review_root)
            elif arguments.field == "handoff-root":
                print(locations.handoff_root)
            elif arguments.field == "adr-log":
                print(locations.adr_log)
            elif arguments.field == "plan":
                print(locations.plan)
            else:
                print(json.dumps({"queue": str(locations.queue), "taskRoots": [str(root) for root in locations.task_roots]}))
        elif arguments.command == "project":
            declaration = read_project_declaration(project_root) or {"version": 1}
            locations = resolve_project_locations(project_root)
            resolved = {
                **declaration,
                "locations": {
                    "queue": str(locations.queue), "taskRoots": [str(root) for root in locations.task_roots],
                    "reviewRoot": str(locations.review_root), "handoffRoot": str(locations.handoff_root),
                    "adrLog": str(locations.adr_log), "plan": str(locations.plan),
                },
            }
            if arguments.field == "reviewer-author":
                project_info = declaration.get("project")
                if not isinstance(project_info, dict):
                    raise CardineError("project declaration key 'project' is required for reviewer-author")
                value = f"{project_info['name']} Reviewer-Integrator <reviewer-integrator@{project_info['slug']}.local>"
            elif arguments.field == "validation-scoping":
                value = declaration.get("validationScoping", [])
            elif arguments.field == "ci":
                value = declaration.get("ci", "none")
            elif arguments.field:
                value = resolved.get(arguments.field)
            else:
                value = resolved
            if arguments.format == "json":
                print(json.dumps(value, sort_keys=True))
            elif isinstance(value, (dict, list)):
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                print(value)
        elif arguments.command == "setup":
            plan = plan_setup(
                arguments.worktree_root,
                arguments.config.expanduser().resolve(),
                task_identity=arguments.task_identity,
                framework_root=framework_root,
                project_root=arguments.project,
            )
            print_setup_plan(plan)
            if arguments.apply:
                changed = apply_setup(plan)
                print("result: updated; restart Codex" if changed else "result: no-op")
        elif arguments.command == "codex":
            resolved_root = resolve_worktree_root(arguments.worktree_root)
            if arguments.codex_command == "configure":
                plan = plan_codex_configuration(
                    arguments.config.expanduser().resolve(),
                    resolved_root.path,
                    arguments.requirements.expanduser().resolve() if arguments.requirements else None,
                )
                print_codex_configuration_plan(plan)
                if arguments.apply:
                    changed = apply_codex_configuration(plan)
                    if changed and plan.status in ("repair-required", "repair-and-replace-required"):
                        action = (
                            "ownership metadata repaired and root replaced"
                            if plan.status == "repair-and-replace-required"
                            else "ownership metadata repaired"
                        )
                        print(
                            f"result: {action}; this does not prove the running session loaded "
                            "the profile, so start a fresh Codex session and probe it"
                        )
                    else:
                        print("result: updated; restart Codex and select the profile" if changed else "result: no-op")
            elif arguments.codex_command == "worktree-path":
                path = task_worktree_path(project_root, resolved_root.path, arguments.task_id)
                validate_worktree_collision(project_root, path, arguments.task_id)
                print("DEPRECATED: use `cardine worktree path`", file=sys.stderr)
                print(path)
            else:
                report = codex_doctor(
                    project_root,
                    arguments.config.expanduser().resolve(),
                    resolved_root.path,
                    framework_root=framework_root,
                )
                for capability, status in report.items():
                    print(f"{capability}: {status}")
        elif arguments.command == "worktree":
            if arguments.worktree_command == "active":
                print(json.dumps(active_worktree_task(Path.cwd()) or {}, sort_keys=True))
            elif arguments.worktree_command == "states":
                print(json.dumps(registered_worktree_task_states(arguments.project), sort_keys=True))
            elif arguments.worktree_command == "path":
                canonical_project = _verified_lifecycle_project(project_root)
                path_identity = resolve_task_identity(
                    canonical_project, arguments.task_id, "existing"
                )
                path = _task_worktree_path_for_identity(
                    canonical_project,
                    _effective_worktree_root(arguments.worktree_root),
                    path_identity,
                )
                validate_worktree_collision(canonical_project, path, arguments.task_id)
                if arguments.format == "json":
                    print(json.dumps({
                        "version": 1,
                        "path": str(path),
                        "handoff_worktree": handoff_worktree_value(
                            _effective_worktree_root(arguments.worktree_root), path
                        ),
                    }, sort_keys=True))
                else:
                    print(path)
            elif arguments.worktree_command == "prepare":
                prepared = prepare_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                    arguments.base,
                    arguments.resume,
                )
                journal.observe(prepared)
                print(json.dumps(prepared, sort_keys=True))
            elif arguments.worktree_command == "repair-base":
                repaired = repair_task_worktree_base(arguments.task_id, arguments.worktree_root, project_root)
                journal.observe(repaired)
                print(json.dumps(repaired, sort_keys=True))
            elif arguments.worktree_command == "check":
                report, ready = inspect_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                    resume=arguments.resume,
                )
                journal.observe(report)
                print(json.dumps(report, sort_keys=True))
                if not ready:
                    mismatch = stop_error(
                        str(report.get("stop_reason", "WRONG_WORKTREE")),
                        "worktree check reported: " + ", ".join(str(error) for error in report["errors"]),
                        resume=report.get("resume"),
                        task_id=arguments.task_id,
                        project=project_root,
                    )
                    journal.stopped(mismatch.code)
                    print(mismatch, file=sys.stderr)
                    return 2
            elif arguments.worktree_command == "evidence":
                recorded = (record_task_evidence(
                    arguments.task_id,
                    arguments.worktree_root,
                    arguments.validation_command,
                    arguments.validation_exit_code,
                    accepted=arguments.accepted,
                    task_dependencies=arguments.task_dependency,
                    task_behavioral_surfaces=arguments.task_behavioral_surface,
                    main_advanced_dependencies=arguments.main_advanced_dependency,
                    main_advanced_behavioral_surfaces=arguments.main_advanced_behavioral_surface,
                    full_validation_required=arguments.full_validation_required,
                    supplied_project=project_root,
                ))
                journal.observe(recorded)
                print(json.dumps(recorded, sort_keys=True))
            elif arguments.worktree_command == "closure-status":
                report, ready = closure_status(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                )
                journal.observe(report)
                if not ready:
                    journal.stopped(str(report["stop_reason"]) if report["stop_reason"] is not None else None)
                if arguments.format == "json":
                    print(json.dumps(report, sort_keys=True))
                elif report["stop_reason"] is not None:
                    print(format_stop(
                        str(report["stop_reason"]),
                        str(load_stop_registry()[str(report["stop_reason"])]["summary"]),
                        resume=str(report["resume"]),
                    ))
                else:
                    print(f"{report['step']}; resume: {report['resume'] or 'none'}")
                if not ready:
                    return 2
            elif arguments.worktree_command == "advance":
                advanced, blocked = advance_task_closure(
                    arguments.task_id,
                    arguments.worktree_root,
                    arguments.validation_command,
                    arguments.validation_exit_code,
                    accepted=arguments.accepted,
                    supplied_project=project_root,
                    candidate_commands=arguments.candidate_command,
                    candidate_exit_codes=arguments.candidate_exit_code,
                )
                journal.observe(advanced)
                print(json.dumps(advanced, sort_keys=True))
                if blocked:
                    journal.stopped(str(advanced["stop_code"]))
                    return 2
            elif arguments.worktree_command == "integrate":
                if arguments.integrate_command == "stage":
                    result = stage_task_integration(
                        arguments.task_id,
                        arguments.worktree_root,
                        arguments.evidence,
                        project_root,
                    )
                elif arguments.integrate_command == "finalize":
                    result = finalize_task_integration(
                        arguments.task_id,
                        arguments.evidence,
                        project_root,
                    )
                else:
                    result = abort_task_integration(arguments.task_id, project_root)
                journal.observe(result)
                print(json.dumps(result, sort_keys=True))
            else:
                cleaned = cleanup_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                )
                journal.observe(cleaned)
                print(json.dumps(cleaned, sort_keys=True))
        elif arguments.command == "review":
            print(json.dumps(record_review_verdict(project_root, arguments.task_id, arguments.verdict,
                                                   owner=arguments.owner, body=arguments.body), sort_keys=True))
        elif arguments.command == "task":
            if arguments.task_command == "new":
                from cardine.tasks.creation import create_task
                from cardine.tasks.contract import _contract_field
                text = arguments.record.read_text(encoding="utf-8")
                if arguments.quick:
                    category = _contract_field(text, "Category")
                    if category and category.lower() != "quick":
                        raise CardineError("--quick conflicts with record Category")
                    if not category:
                        text = "Category: Quick\n" + text
                print(json.dumps(create_task(project_root, arguments.task_id, text,
                                             recover=arguments.recover), sort_keys=True))
            elif arguments.task_command == "contract":
                from cardine.tasks.contract_update import update_task_contract
                print(json.dumps(update_task_contract(project_root, arguments.task_id), sort_keys=True))
            elif arguments.task_command == "transition":
                print(json.dumps(transition_task_state(project_root, arguments.task_id, arguments.status,
                    cancellation_authority=arguments.cancellation_authority, reason=arguments.reason), sort_keys=True))
            elif arguments.task_command == "outcome":
                from cardine.tasks.transitions import record_spike_outcome
                print(json.dumps(record_spike_outcome(project_root, arguments.task_id, arguments.outcome), sort_keys=True))
            elif arguments.task_command == "close":
                print(json.dumps(close_task(project_root, arguments.task_id), sort_keys=True))
            elif arguments.task_command == "state":
                print(json.dumps(import_task_states(project_root, arguments.task_ids, apply=arguments.apply,
                                                  include_terminal=arguments.include_terminal), sort_keys=True))
            elif arguments.identity_command == "check":
                resolved = resolve_task_identity(project_root, arguments.task_id, "existing")
                print(json.dumps(task_identity_json(project_root, resolved), sort_keys=True))
            else:
                resolved = next_milestone_task_identity(
                    project_root, arguments.milestone, arguments.workstream
                )
                print(json.dumps(resolved.as_json(project_root), sort_keys=True))
        elif arguments.command == "validation":
            report, exit_code = check_validation_evidence(
                arguments.record, canonical_project_root(project_root), arguments.commit
            )
            print(json.dumps(report, sort_keys=True))
            return exit_code
        elif arguments.command == "adr":
            if arguments.adr_command == "list":
                listed, adr_warnings = adr_list(project_root, arguments.status)
                for adr_warning in adr_warnings:
                    print(f"warning: {adr_warning}", file=sys.stderr)
                if arguments.format == "json":
                    print(json.dumps(listed, sort_keys=True))
                else:
                    for entry in listed:
                        print(f"{entry['id']}\t{entry['title']}\t{entry['status'] or '-'}")
            else:
                print(adr_show(project_root, arguments.adr_id))
        elif arguments.command == "context":
            if arguments.context_command == "authority":
                print(context_authority(project_root, arguments.task_id, arguments.labels_only))
            else:
                if arguments.threshold_bytes is not None and arguments.threshold_bytes < 0:
                    raise CardineError("--threshold-bytes must be a non-negative integer")
                report = context_size_report(project_root, arguments.role, arguments.context_task_id, arguments.threshold_bytes)
                print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_context_size_report(report))
                return 2 if report["exceeded"] else 0
        elif arguments.command == "usage":
            report = usage_report(arguments.host, arguments.project, arguments.since, arguments.breakdown)
            print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_usage_report(report))
            return 0 if report["status"] == "ok" else 2
        elif arguments.command == "execution":
            if arguments.execution_command == "start":
                print(json.dumps(execution_start(project_root, arguments.task_id, resume=arguments.resume), sort_keys=True))
            elif arguments.execution_command == "deliver":
                print(json.dumps(execution_deliver(project_root, arguments.task_id), sort_keys=True))
            elif arguments.execution_command == "contract":
                print(execution_contract(project_root, arguments.task_id))
            elif arguments.execution_command == "reconcile":
                print(reconcile_execution_contract(project_root, arguments.task_id, arguments.apply))
            elif arguments.execution_command == "preflight":
                print(execution_preflight(project_root, arguments.task_id))
            elif arguments.execution_command == "validate":
                return run_validation(project_root, arguments.task_id, arguments.validation_id)
            elif arguments.execution_command == "ready-check":
                if state_path(project_root, arguments.task_id).exists():
                    result = delivery_readiness(project_root, arguments.task_id)
                    print(json.dumps(result, sort_keys=True))
                else:
                    print(readiness_check(project_root, arguments.task_id, (project_root / arguments.report if arguments.report else default_handoff_path(project_root, arguments.task_id))))
            else:
                print(check_handoff(project_root, arguments.task_id, (project_root / arguments.report if arguments.report else default_handoff_path(project_root, arguments.task_id))))
        elif arguments.command == "hook":
            if arguments.hook_command == "read-guard" and arguments.host == "codex":
                from codex_read_guard import main as codex_read_guard_main

                return codex_read_guard_main()
            if arguments.hook_command == "stop-audit":
                from stop_audit import main as stop_audit_main

                return stop_audit_main(arguments.host)
        elif arguments.check:
            if arguments.owner_reconciled:
                raise CardineError("--owner-reconciled only applies to --apply")
            base_manifest, target_override, managed_override = prepare_upgrade_targets(
                project_root, framework_root, arguments.stop_before_retirement
            )
            installed_version = manifest_baseline_version(base_manifest)
            manifest, plan = plan_from_baseline(
                project_root,
                framework_root,
                manifest_workflow_mode(base_manifest),
                installed_version,
                project_root / names().baselines_path / installed_version,
                list(base_manifest.get("appliedMigrations", [])),
                target_version_override=target_override,
                managed_files_override=managed_override,
                installed_framework_version=str(base_manifest.get("frameworkVersion", "")),
                capability_profiles=base_manifest.get("capabilityProfiles"),
            )
            print_plan(project_root, manifest, framework_root, plan, target_version_override=target_override)
            for advisory in retired_text_advisories(project_root, framework_root, base_manifest):
                print(f"{advisory.status:14} {advisory.identity} — {advisory.detail}")
            if plan_has_blockers(plan):
                return 2
        else:
            apply_upgrade(
                project_root,
                framework_root,
                arguments.owner_reconciled,
                arguments.stop_before_retirement,
            )
    except CardineStop as error:
        if getattr(error, "recovery_worktree", None) is not None:
            # Preserve the exact invocation, including optional flags and values.
            rerun = []
            tokens = iter(sys.argv[1:])
            for token in tokens:
                if token == "--project":
                    next(tokens, None)
                elif not token.startswith("--project="):
                    rerun.append(token)
            rerun.extend(("--project", str(error.recovery_worktree)))
            detail = error.recovery_detail
            if str(arguments.project) != str(project_root):
                detail = detail.replace(f"--project={project_root};",
                                        f"--project={arguments.project}; resolved project={project_root};", 1)
            error = stop_error(error.code, detail, resume=shlex.join(("cardine", *rerun)))
        journal.stopped(error.code)
        print(error, file=sys.stderr)
        return 2
    except CardineError as error:
        refused = stop_error("COMMAND_REFUSED", str(error))
        journal.stopped(refused.code)
        print(refused, file=sys.stderr)
        return 2
    except OSError as error:
        failed = stop_error("OS_ACCESS_FAILED", str(error))
        journal.stopped(failed.code)
        print(failed, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
