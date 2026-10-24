"""Read-only non-run cause resolution; never retries an installation effect.

Missing/busy paths are nonhuman only for explicit diagnostic invocations.
Apply failures, denied access, corrupt markers, foreign edits and unknown errors
remain guardrails. SR1 owns reconciliation of existing installation effects.
No local path, receipt or digest establishes authorship or grants consent.
"""

from __future__ import annotations

import errno


def os_stop_code(error: OSError, *, diagnostic: bool = False) -> str:
    """Classify a measured errno without guessing ownership of a failed write."""
    if diagnostic:
        if error.errno == errno.ENOENT:
            return "OS_PATH_MISSING"
        if error.errno in {errno.EBUSY, errno.ETXTBSY}:
            return "OS_PATH_BUSY"
    return "OS_ACCESS_FAILED"


def diagnostic_invocation(arguments: object) -> bool:
    """Only explicitly read-only upgrade/host checks permit a safe rerun.

    A missing apply argument or an unrelated command does not prove that no
    effect preceded the error. Never turn their residue into automatic repair.
    """
    command = getattr(arguments, "command", None)
    if command in {"upgrade", "setup"}:
        return bool(getattr(arguments, "check", False)) and not getattr(arguments, "apply", False)
    if command == "codex":
        subcommand = getattr(arguments, "codex_command", None)
        return subcommand in {"doctor", "worktree-path"} or (
            subcommand == "configure" and bool(getattr(arguments, "check", False))
            and not getattr(arguments, "apply", False)
        )
    return False


# Emitter-to-cause audit for the non-run row. The tests enumerate every refuse
# call (including dynamic forwarding), upgrade diagnostic and host catch.
# Existing effect boundaries are observed, never replayed by these classifiers:
# update: fetch / fast-forward or detach / final HEAD+VERSION verification;
# upgrade: managed writes / generated outputs / baseline / manifest;
# Codex: exclusive backup / temporary write / atomic replacement.
NONRUN_CAUSES = {
    "SELF_UPDATE_PLUGIN_CACHE": ("recoverable", "route to the plugin manager; do not run it or grant home-write consent"),
    "SELF_UPDATE_DIRTY": ("guardrail", "foreign edits or unproven residue; preserve every file"),
    "SELF_UPDATE_BRANCH": ("guardrail", "development branch or explicit stable rollback needs a strategy decision"),
    "SELF_UPDATE_INPUT_INVALID": ("failing-work", "invalid target argument; correct the requested argument before retry"),
    "SELF_UPDATE_TARGET": ("guardrail", "unpublished/mismatched release, unresolved refs or non-fast-forward ancestry"),
    "SELF_UPDATE_VERIFY": ("guardrail", "unknown Git/apply residue or changed final identity; SR1 owns pinned recovery"),
    "UPGRADE_BLOCKED": ("guardrail", "project conflict or missing consumer-owned router requirements"),
    "UPGRADE_OUTPUT_PENDING": ("recoverable", "validated generator can plan absent output; apply still requires its existing authority"),
    "COMMAND_REFUSED": ("guardrail", "uncoded input/state failure or damaged host markers; no inferred repair authority"),
    "OS_ACCESS_FAILED": ("guardrail", "permission denial, unknown error or any failed effect with unproven residue"),
    "OS_PATH_MISSING": ("failing-work", "ENOENT in an explicit read-only check; no write or deletion"),
    "OS_PATH_BUSY": ("recoverable", "EBUSY/ETXTBSY in an explicit read-only check; rerun that check, never apply"),
}
