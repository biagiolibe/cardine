# Troubleshooting

Replace `<TASK-ID>`, `<primary-checkout>`, and other placeholders with the values in your output. Follow the printed `next.command` or `stop.resume` when it differs from these examples.

## CI

### No check run for the delivered commit

**What you see:** `waiting` with `CI_NOT_STARTED`, or a `CI_NOT_STARTED` stop after the wait expires.

**Why:** The provider has not started a required check for the delivered SHA.

**What to do:** Trigger the workflow by pushing the same SHA to a branch it accepts, using the delivered ref from the diagnostic: `git push origin <delivered-sha>:<delivered-ref>-ci`. Then run the printed `stop.resume`, for example `cardine run <TASK-ID> --project <primary-checkout> --ci-wait-seconds <seconds>`.

### Documentation changes do not trigger CI

**What you see:** `CI_NOT_STARTED` for a documentation-only commit.

**Why:** A `paths-ignore` filter skipped all changed paths. Another branch with the same filter will also skip the SHA.

**What to do:** Adjust, commit and publish the workflow trigger; trigger CI for the delivered SHA and resume with `cardine run <TASK-ID> --project <primary-checkout>`.

## Review

### Approval is missing, stale, or from the wrong source

**What you see:** `REVIEW_NOT_APPROVED` with `cause: missing`, `cause: stale`, or `cause: source`.

**Why:** Review or required CI is missing, review inputs changed, or frozen `reviewSources` excludes owner.

**What to do:** Run `cardine run <TASK-ID> --project <primary-checkout>` for CI and current independent review from an allowed source. If allowed, the developer can record a verdict in a terminal with `cardine review verdict <TASK-ID> APPROVE --owner --project <primary-checkout>`. Retry the interrupted command.

### Launched reviewer is unavailable

**What you see:** `launched reviewer unavailable: role-launch-reviewer is <status>` or `launched reviewer unavailable: review.reviewer is missing on main`.

**Why:** The host is unconfigured or its launch boundary is not ready.

**What to do:** Run `cardine doctor --host <host> --project <primary-checkout>` and fix the host setup or missing `review.reviewer` on main. Then run `cardine run <TASK-ID> --project <primary-checkout>`. If allowed, the developer can instead use `cardine review verdict <TASK-ID> APPROVE --owner --project <primary-checkout>` after review.

### Review budget exhausted

**What you see:** `REVIEW_LOOP_EXHAUSTED: two consecutive changes-requested rounds require a new budget decision`.

**Why:** Two consecutive `CHANGES_REQUESTED` rounds left findings unresolved.

**What to do:** Give the developer the review record and unresolved findings for a scope or authority decision. After the decision and any necessary task changes, restart the lifecycle with `cardine run <TASK-ID> --project <primary-checkout>`; do not fabricate a verdict.

## Policy and authority

### Project policy changed

**What you see:** `developer reauthorization required` or `task-policy: <ID> predates main; cardine run <ID> will merge main`.

**Why:** Authority follows the declaration on main; tasks can have older policy or contracts.

**What to do:** Commit `.cardine/project.json` on main. In the developer terminal run `cardine authorize --check --project <primary-checkout>`, then `cardine authorize --apply --project <primary-checkout>`. To update the contract, run `cardine task contract update <TASK-ID> --project <task-worktree>`. Commit work; run `cardine run <TASK-ID> --project <primary-checkout>` to refresh.

### A necessary file is outside the expected surface

**What you see:** A needed path is outside the frozen Expected code surface, or `SCOPE_CHANGE_REQUIRED` lists it.

**Why:** The contract limits changed files.

**What to do:** Request approval for exact paths, reasons, and validation changes before editing. After approval, update the task record in its worktree and run `cardine task contract update <TASK-ID> --project <task-worktree>`. Then edit the approved files and resume with `cardine run <TASK-ID> --project <primary-checkout>`.

## Integration

### Spike outcome required

`SPIKE_OUTCOME_REQUIRED` asks the developer to judge the committed deliverable. Run:

```sh
cardine task outcome <ID> ANSWERED --project <worktree>
cardine run <ID> --project <primary>
```

Use `INCONCLUSIVE` instead of `ANSWERED` when appropriate.


### Refresh from main conflicts

**What you see:** `INTEGRATION_CONFLICT` during refresh from main.

**Why:** The automatic merge encountered a textual conflict and was aborted.

**What to do:** In the task worktree, the developer runs `git merge main`, resolves and commits the conflict, then runs `cardine run <TASK-ID> --project <primary-checkout>`.

## Updates and console

### Runtime update requires reauthorization

**What you see:** `developer reauthorization required: executing runtime changed`.

**Why:** The installed runtime no longer matches the accepted authority.

**What to do:** Restart running agent sessions. In the developer terminal run `cardine authorize --check --project <primary-checkout>` and `cardine authorize --apply --project <primary-checkout>`, then resume with `cardine run <TASK-ID> --project <primary-checkout>`.

### Latest release is unknown

**What you see:** `Latest: unknown (<reason>)` from `cardine self-update`.

**Why:** The latest release could not be determined. Older versions before 0.10.0 may not understand a release's metadata; a network failure can also cause this message.

**What to do:** Check the [releases](https://github.com/biagiolibe/cardine/releases), then use the manual update command printed by the CLI. For a pipx installation, select a release and run `pipx install --force 'git+https://github.com/biagiolibe/cardine@v<version>'`. Retry `cardine self-update --check`.

### Landed task remains Closing

**What you see:** `Closing` with `CLEANUP_BLOCKED` for a landed task in an older console.

**Why:** Before task 285, a file such as `.DS_Store` in the old worktree placeholder could make completed cleanup appear unfinished.

**What to do:** Update Cardine with `cardine self-update --apply`, restart the console, and run `cardine console --project <primary-checkout>`. Inspect a genuine remaining cleanup block before removing any file.
