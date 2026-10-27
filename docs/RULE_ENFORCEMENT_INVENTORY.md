# Rule enforcement inventory

Task 074, decision 14 rule 1 of `docs/ADR_CARDINE_1_0.md`. Taken on `main` commit
`a0ab0719b7facf0de6db2da04f6a7e5a25806cd5`. No code, template, or test changed.

Rule 1 says an agent needs little to read, and that every rule in the templates
is enforced by the tool and stated in one line, labelled as advice, or deleted;
no rule whose violation causes harm exists only in prose. This document lists
every rule an agent is told, how the tool enforces it, and what to do with it,
and sets a size budget for what an agent reads on every task.

Text gates (gates that read record, handoff, report, queue, or plan text) are
inventoried in `docs/TEXT_GATE_INVENTORY.md` (task 073) and are cited here by
their entry ID (`T-nn`, `TPL-nn`), not repeated. Hand-edited state, forged
evidence, and every other forgery are inventoried by task 075; stop codes the
tool could resolve itself are reviewed by task 076. Where an entry depends on
either, it names the task and does not plan the defense.

## Summary

- **Size.** The single template set is 21,367 words in 23 files. An agent told
  `Proceed with <ID>` reads 7,220 words before it starts; the smallest role
  reads 4,432. The proposed budget is 1,100 words for what every task reads,
  1,400 for any role at start, and 5,600 for the whole set. The actions below
  reach 5,534 words in total and 1,111 to 1,336 per role at start
  (see "Word budget").
- **Entries.** 268 rules, one entry each: 31 `enforce`, 38 `one line`, 40
  `advice`, 145 `delete`, 14 `moved`. A gate or host rule is named for 146 of
  them, 30 repeat another entry's gate, and 74 have none. 55 of the deletions
  name an engine row, because `cardine run` returns the next action, resolves
  the directory, runs validation, and lands.
- **Rules with harm and no gate** (the 12 `enforce` entries with no
  enforcement at all, and the gaps in 19 more): an implementer can approve its
  own work, because `review verdict` never identifies the caller and `--owner`
  is a flag (PW-21, PW-46, RV-17, HX-04); a hand-written state file passes every
  gate (PW-10, PW-53); the agent counts validation failures and declares exit
  codes (PW-51, PW-55); nothing compares changes with the expected code surface
  (PW-36g, TB-06); nothing detects a concurrent writer in a worktree (PW-32);
  and on both hosts the agent may push `main` or fast-forward a branch into it
  without reaching `integrate stage` (PW-36b, PW-36e).
- **Contradictions.** Seven passages tell the agent to stop on codes whose
  registry entry says it must not (CX-01); `INTEGRATION_POLICY.md` tells the
  agent to run `git push origin --delete`, which both hosts refuse (CX-10); and
  the repository check pins template prose that this document proposes to
  delete (CX-13). Fifteen contradictions in all.
- **Destinations.** Existing rows RE1 to RE6, SS6, and N2 cover most findings.
  Nine one-sentence amendments close the rest (A-RE1-1 to A-RE7-1). Three new
  rows: RX1 (remove the counters decision 5 removed), TR1 (rewrite the
  always-read set to the budget), TR2 (condense the reference documents).
  Host findings go to work item 9, which no row plans.

## How it was taken

All commands run from the repository root at the commit above, in a task
worktree. The measurements use only `templates/single/` and `src/cardine/`.

```bash
# R1 files and words (the 21,367-word total of decision 14)
find templates/single -type f | xargs wc -w | sort -k2
find templates/single -type f | xargs cat | wc -w

# R2 words per managed block and capabilities repeated in several files
python3 - <<'PY'
import pathlib, re, collections
root = pathlib.Path("templates/single")
pat = re.compile(r"<!-- CARDINE:BEGIN capability=(\S+) v\d+ -->(.*?)<!-- CARDINE:END -->", re.S)
by_cap = collections.defaultdict(list)
for p in sorted(root.rglob("*.md")):
    t = p.read_text(encoding="utf-8")
    inblock = 0
    for m in pat.finditer(t):
        inblock += len(m.group(2).split())
        by_cap[m.group(1)].append((str(p.relative_to(root)), len(m.group(2).split())))
    print(p.relative_to(root), len(t.split()), inblock)
for cap, v in sorted(by_cap.items()):
    if len(v) > 1:
        print("DUP", cap, len(v), sum(w for _, w in v), [f for f, _ in v])
PY

# R3 what an agent reads at start, per role (router, always-read, routed workflow, deferred)
S=$(mktemp -d); cp -R templates/single/. "$S"; mkdir "$S/.cardine"
echo '{"version": 1, "preset": "lean"}' > "$S/.cardine/project.json"
for r in status design implementation review remediation lifecycle; do
  PYTHONPATH=src python3 -c "import sys; from cardine.cli import main; \
sys.argv=['cardine','context','size','--role','$r','--format','text','--project','$S']; sys.exit(main())"
done

# R4 every backticked `cardine <command>` in the templates against the argparse tree
PYTHONPATH=src python3 - <<'PY'
import argparse, pathlib, re, sys
from cardine import cli
def walk(p, prefix=()):
    out = set()
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                out.add(prefix + (name,)); out |= walk(sp, prefix + (name,))
    return out
known = walk(cli.build_parser())
pat = re.compile(r"`(?:cardine|meridian)\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*)?(?:\s+[a-z][a-z-]*)?)")
for path in sorted(pathlib.Path("templates/single").rglob("*")):
    if path.is_file() and path.suffix in {".md", ".rules", ".json"}:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in pat.finditer(line):
                w = tuple(m.group(1).split())
                if not any(w[:k] in known for k in (3, 2, 1) if len(w) >= k):
                    print(path, n, " ".join(w))
PY

# R5 stop registry classes (51 codes, 27 guardrails) and who emits each
python3 -c "import json; d=json.load(open('capabilities/stop-codes-v1.json'))['stops']; \
print(len(d), sum(1 for x in d if x['human_decision'])); \
[print(x['code'], x['human_decision'], x['emitter'][:70]) for x in d]"
git grep -n 'REVIEW_REQUIRED\|PUSH_REJECTED\|REVIEW_LOOP_EXHAUSTED\|SCOPE_CHANGE_REQUIRED\|RULE_CONFLICT\|WORKFLOW_UNREADABLE\|VALIDATION_RETRY_LIMIT\|ACCEPTANCE_UNMET' -- src scripts

# R6 host assets installed by setup and the plugin
sed -n 49,290p src/cardine/hosts/setup.py          # plan_setup: what `cardine setup` installs
sed -n 13,76p src/cardine/hosts/claude.py          # Claude allow and deny lists
sed -n 23,56p src/cardine/hosts/codex.py           # Codex user rules
find skills commands hooks .claude-plugin -type f | xargs wc -w
cat templates/single/.codex/rules/meridian.rules templates/single/.codex/hooks.json

# R7 the entry tables are checked by the script in the "Self-check" section below
```

The line numbers in the entry tables are lines of the file as of this commit.
A line range names the sentence or paragraph, not the whole section.

## Files and when an agent reads them

Word counts are from R1. "Always" means every task of every role (router,
workflow, language policy). "Role" means the routed procedure of one trigger.
"Phase" means a document the routed procedure reads at a named phase
(`capability=phase-reads`). "Demand" means no routed procedure makes the agent
read it. In the terms of the task contract, Always is what an agent reads on
every task, Role and Phase together are what it reads on some tasks, and
Demand is what it reads only on demand. The router read set is what `cardine
context size` reports (R3).

| File | Words | Read class | By whom |
|------|------:|------------|---------|
| `AGENTS.md` / `CLAUDE.md` | 180 / 129 | Always | Codex / Claude Code; the host loads it |
| `PROJECT_WORKFLOW.md` | 3,468 | Always | every role |
| `LANGUAGE_POLICY.md` | 186 | Always | every role |
| `docs/workflows/IMPLEMENTATION.md` | 1,660 | Role | `Proceed with` |
| `docs/workflows/REVIEW.md` | 1,637 | Role | `Review` |
| `docs/workflows/REMEDIATION.md` | 598 | Role | `Address review` |
| `docs/LIFECYCLE_ORCHESTRATION.md` | 1,463 | Role | `Run lifecycle`, `Accept`, `Restart rejected`; remediation on an unremediable finding |
| `docs/CONTEXT_READING_POLICY.md` | 1,726 | Role | status, design; implementation at start |
| `docs/CODE_ORGANIZATION.md` | 608 | Phase | first production-source plan, hunk, or change |
| `tasks/TASK_BLUEPRINT.md` | 1,320 | Phase | proposing a spike; task authors |
| `docs/EXECUTION_EVIDENCE_PROFILE.md` | 491 | Phase | first validation |
| `docs/COMPLETION_REPORT_TEMPLATE.md` | 728 | Phase | completion |
| `docs/REVIEW_RECORD_TEMPLATE.md` | 345 | Phase | at verdict |
| `docs/WORKTREE_LIFECYCLE.md` | 1,561 | Phase | linked anchor `#command-locations` before `execution start`; whole file never routed |
| `docs/INTEGRATION_POLICY.md` | 1,048 | Demand | cited by `CODE_REVIEW_PROMPT.md` and the completion template |
| `docs/CODE_REVIEW_PROMPT.md` | 686 | Demand | a prompt the reviewer is given |
| `docs/AUDIT_PROMPT_READ_ONLY.md` | 663 | Demand | explicit audit |
| `docs/OPERATOR_PROMPTS.md` | 1,637 | Demand | developer cookbook |
| `docs/ARCHITECTURE_DECISIONS.md`, `README.md`, `TECH_DESIGN.md`, `PROJECT_PLAN.md`, `tasks/QUEUE.md`, `.gitignore`, `.claudeignore` | 25, 183, 183, 154, 88, 19, 35 | Demand | fill-in or generated; they state no rule |
| `.codex/rules/meridian.rules`, `.codex/hooks.json` | 499, 47 | Host | read by Codex, not by the agent |
| Total of `templates/single/` | **21,367** | | |

Measured start read sets (R3, bytes in parentheses): implementation 7,220 words
(51,602), review 5,471 (39,619), remediation 4,432 (32,114), status and design
5,560 (39,642), lifecycle 6,934 (50,482). The ceiling that `check_repository.py`
enforces for each role is 100,000 bytes (`CONTEXT_READING_POLICY.md:199-206`),
so no role is near it and the ceiling constrains nothing.

Host assets that product setup installs or the plugin delivers, outside
`templates/single/` (R6):

| Asset | Words | How it reaches an agent |
|-------|------:|-------------------------|
| `skills/meridian-lean-delivery/SKILL.md`, `meridian-governed-sdd/SKILL.md` | 491; 1,304 | `cardine setup --apply` symlinks them for Codex (`hosts/skills.py:30,33`) |
| `skills/*-claude-code/SKILL.md` | 461; 1,419 | the Claude Code plugin |
| `commands/meridian-{init,task,audit,upgrade,adopt}.md` | 804; 530; 262; 374; 39 | the Claude Code plugin slash commands |
| `hooks/queue-briefing.sh`, `read-guard.sh`, `stop-audit.sh`, `hooks.json` | code | the plugin; no agent reads them; the briefing prints a few lines each turn |
| Codex user rules block | 25 lines | `cardine setup --apply` (`hosts/codex.py:23-56`) |
| Claude project allow and deny lists | 45 allow + 11 deny entries | `cardine setup --apply` (`hosts/claude.py:13-76`) |

## Enforcement keys

An entry names the gate that enforces its rule. A key is a gate that can refuse,
not a command that merely exists. `Host` keys depend on the agent host and are
split by host where they differ.

| Key | Gate | Where | What it refuses |
|-----|------|-------|-----------------|
| G01 | `worktree check` | `worktree/checkout.py::inspect_task_worktree:199` | wrong path, branch, HEAD, base, or dirty worktree (`WRONG_WORKTREE`) |
| G02 | `worktree prepare` | `checkout.py::prepare_task_worktree:72` | partial or mismatched state, existing dirty worktree without `--resume` |
| G03 | `execution start` | `lifecycle/commands.py::execution_start:24` | start in the wrong worktree; records `queued → in_progress` |
| G04 | `execution deliver`, `ready-check` | `commands.py::execution_deliver:61`, `lifecycle/execution.py::delivery_readiness:196` | delivery without clean committed HEAD, validation, and handoff |
| G05 | `task close` | `tasks/transitions.py::close_task:70` | closure from a dirty or unregistered worktree |
| G06 | `review verdict` | `review/verdict.py::record_review_verdict:23` | wrong branch, status not `in_review`, implementation changed after submission (`REVIEW_STALE`, `:101`). It does not identify the caller. |
| G07 | `integrate stage` | `integration/merge.py::stage_task_integration:156` | dirty primary, held lease, main behind origin (`:215`), conflict (`:310`), unapproved review (`:131`), stale review (`:137,150`), evidence mismatch (`:289`) |
| G08 | `integrate finalize` | `merge.py::finalize_task_integration:375` | candidate tree changed or evidence stale (`:394,398`), undeclared candidate commands (`:413`) |
| G09 | `integrate abort` | `merge.py::abort_task_integration:477` | not an owned integration |
| G10 | `worktree cleanup` | `merge.py::cleanup_task_worktree:500` | active lease, unmerged or dirty state (non-force) |
| G11 | `worktree advance` | `lifecycle/closure.py::advance_task_closure:55` | missing C1–C10 evidence |
| G12 | `decide_integration_validation` | `integration/decision.py:30` | selects REUSE, BOUNDED, or FULL; material interaction |
| G13 | `execution validate` | `tasks/recording.py::run_validation:38` | runs only a task-declared literal command and records its exit status |
| G14 | `execution preflight`, `contract` | `tasks/preflight.py::execution_preflight:44`, `tasks/contract.py` | missing record headings, host-impact shape (text gates of task 073) |
| G15 | stop registry and renderer | `stops/registry.py::load_stop_registry`, `stops/render.py` | prints `BLOCKED <CODE>` only through the registry |
| G16 | Stop hook audit | `scripts/stop_audit.py::audit` | nothing: it journals `BLOCKED` reports and always exits 0 |
| G17 | Codex read guard | `scripts/codex_read_guard.py` via `cardine hook read-guard --host codex` | a Bash read of a large file without a range; Codex only (`cli.py:850`) |
| G18 | plugin shell hooks (Claude Code) | `hooks/hooks.json`: `queue-briefing.sh`, `read-guard.sh` (Read tool), `stop-audit.sh` | a large `Read` without a range; installed by the plugin, not by `cardine setup`; named Meridian until work item 9 |
| G19 | Claude Code allow and deny lists | `hosts/claude.py::CLAUDE_PROJECT_ALLOWLIST:13`, `CLAUDE_PROJECT_DENYLIST:64` | listed prefixes only; anything unlisted prompts |
| G20 | Codex project rules | `.codex/rules/meridian.rules` | `allow`, `prompt`, `forbidden` on leading tokens only (file lines 10-18, 45) |
| G21 | Codex user rules | `hosts/codex.py::CODEX_USER_RULES:23` | force, delete, and mirror pushes; leading tokens only |
| G22 | task creation | `tasks/creation.py`, `tasks/contract.py::resolve_task_contract` | invalid contract; freezes resolved options in the state file |
| G23 | status service | `tasks/status.py` | startability from state and dependencies |
| G24 | context size and ceiling | `shared/context.py`, `scripts/check_repository.py:111-130` | advisory report; a 100,000-byte ceiling per role |
| G25 | transitions and spike outcome | `tasks/transitions.py::transition_task_state:23`, `record_spike_outcome:103`; `tasks/state.py` | transitions outside the table; invalid schema |
| G26 | managed-block integrity | `templates/marker_audit.py` | edits to marker text (byte for byte) |

`PRM` means the host asks the person (an unlisted command): a gate only while a
person is present, absent in an unattended run. `REM` means a reminder: the
per-turn briefing prints the language policy but refuses nothing. `NONE` means
no gate, hook, or deny rule.

## Reading the entry tables

Columns: **ID**, **Lines** (file and lines), **Rule** (in a few words),
**Enforcement** (key, or `NONE`), **Harm** (what a violation causes when no gate
refuses it; `—` when a gate does), **Action**, **Keep** (words the rule keeps in
the always-read or role file after the action; 0 when deleted or moved), and
**Destination**.

Actions follow the task contract:

- **enforce**: the rule is not enforced and a violation causes harm. The
  destination names the gate to add and its row. The rule is stated in one
  line after the gate exists (`Keep`).
- **one line**: already enforced; the prose shrinks to one line.
- **advice**: a violation causes no harm to state, evidence, history, or the
  remote; labelled as advice. The harm cell says why.
- **delete**: duplicated, obsolete, or describing what `cardine run` will do
  for the agent.
- **moved**: belongs to a document an agent reads only on demand (words are
  counted there, in the word budget).

Destination labels: `SS4` to `SS7` are rows of `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md`;
`RE1` to `RE7` are rows of `docs/RUN_ENGINE_PLAN.md`; `N1`, `N2`, `N3` are rows of
`docs/TEXT_GATE_INVENTORY.md` (queue tasks 079 and 080 are N1 part 1 and part 2;
N3 is not yet a task); `TR1` and `TR2` are the new rows proposed under "Destinations";
`H9` is work item 9 (hosts), which has no plan yet; `W10` is work item 10.
`A-RE3-1` and similar are one-sentence amendments listed under "Destinations".

## Entries: workflow, routers, language policy

### `PROJECT_WORKFLOW.md` (PW) and routers (RT)

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| PW-01 | 3-10 | Read the workflow and the router before any edit, Git mutation, task choice, or completion claim | HOST: the host loads CLAUDE.md or AGENTS.md; no Cardine gate | none: every lifecycle effect passes a CLI gate whatever was read | one line | 20 | TR1 |
| PW-02 | 8-10 | Global, home-directory, remembered, or generic instructions are not authority for lifecycle, status, queue format, branch procedure, or review | NONE | none: a CLI gate decides each transition and ignores where the instruction came from | delete | 0 | TR1 (one lifecycle; nothing else to select) |
| PW-03 | 12-15 | The preset supplies defaults only; "update the queue" authorizes nothing else | G22 (options resolved once, frozen in state) | — | delete | 0 | TR1 (the queue is generated, SS4) |
| PW-04 | 15-17 | Missing or contradictory workflow documents or configuration: `BLOCKED WORKFLOW_UNREADABLE`, change nothing | NONE (registry emitter is "agent judgment"; no source emits it, R5) | none: no gate depends on the documents being readable; the CLI refuses without `.cardine/project.json` | delete | 0 | TR1; 076 (remove the code) |
| PW-05 | 20-34 | Preset table: review, authority, and expected-surface defaults; a task overrides either way; a project change affects new tasks only | G22 | — | one line | 25 | TR1 |
| PW-06 | 36-44 | Task contract fields; a quick task is registered; an omitted optional section grants nothing | G22 (schema), G14 (record headings: text gates of task 073) | — | one line | 25 | TR1; N1/N2 (the gates read state) |
| PW-07 | 46-59 | Document precedence of seven items; never resolve a conflict silently | NONE | none: a conflict is visible in review; no gate, state, or verdict depends on it | advice | 45 | TR1; item 5 names the queue as an authority (CX-04) |
| PW-08 | 62-70 | Lifecycle diagram, including spike and cancellation | G25 (transition table) | — | one line | 45 | TR1 |
| PW-09 | 72-78 | `in_review` only with review required; a new commit invalidates approval; `done` only through landing; dependency satisfaction | G06 (`verdict.py:101`), G07 (`merge.py:131`), G23 | — | one line | 35 | TR1 |
| PW-10 | 80 | The state file is the only status and verdict authority; never edit one by hand, including the JSON | NONE for detection: the schema is validated on read, a hand-written valid state passes (decision 14: it passed every command until integration) | a forged status or verdict passes every gate | enforce | 20 | 075 names the defense; RE1 receipts cover engine writes only, so no row detects a foreign write (A-RE1-1) |
| PW-11 | 80 | Commands update projections; agents never load state files | NONE | none: context cost only | delete | 0 | SS5, SS6 (projections end); `cardine status` |
| PW-12 | 80 | Adopt legacy tasks with `task state import`, inspect, then `--apply` | CLI: `tasks/importer.py` runs only when invoked | — | moved | 0 | W10 |
| PW-13 | 80-84, 250 | Task branches never edit queue, archive, or plan; `integrate stage` applies status; in-progress is derived from branch, worktree, and unarchived record | G07 refuses a conflict only (`merge.py:310`); a clean edit of a shared file merges | none after SS4 and SS6: the queue is generated, records do not move, and `stage` no longer writes status. The text is false by then | delete | 0 | SS6, SS4 name the code; template text TR1 (CX-05) |
| PW-14 | 88-98 | List of execution assets | NONE | none | delete | 0 | TR1 (duplicates the router and the file list) |
| PW-15 | 100 | Start with the router, then only the assigned task and its cited sources | G17/G18 refuse large unranged reads only | none: reading more costs context, not integrity | delete | 0 | duplicate of CR-02 |
| PW-16 | 102-107 | Canonical locations; `cardine locations` is authoritative; other documents name a location by role | `cardine locations` (`tasks/identity.py::resolve_project_locations`) | — | one line | 25 | TR1 |
| PW-17 | 110-118 | `taskIdentity.mode` is opaque or milestone; Cardine resolves IDs | `tasks/identity.py` resolver | — | delete | 0 | TR1 (describes the tool) |
| PW-18 | 124-127 | Four roles: tech designer, implementer, reviewer-integrator, orchestrator | NONE | none: `cardine run` returns `work.role` | delete | 0 | RE4; TR1 |
| PW-19 | 125 | The implementer records task status in the task record by its review policy | NONE; contradicts PW-10 | an agent hand-edits a status | delete | 0 | TR1 (CX-06) |
| PW-20 | 125 | The implementer never works in the primary checkout | G01 when run first; G07 refuses a dirty primary (`PRIMARY_DIRTY`) | — | one line | 15 | RE1 (`work.worktree` names the directory) |
| PW-21 | 126 | The reviewer is independent: fresh session, same worktree after the implementer stops; every verdict through the command | G06 binds a verdict to the branch and HEAD but never identifies the caller | an implementer approves its own work and unreviewed code lands | enforce | 25 | RE4 (scope text forbids self-approval without a mechanism: A-RE4-1); 075 |
| PW-22 | 127 | An orchestrator coordinates and never implements or reviews | NONE | none: `cardine run` is the coordinator (decision 6) | delete | 0 | RE4 |
| PW-23 | 129 | Five command triggers and their meaning | NONE (conventions) | none | one line | 40 | TR1 (`Proceed with <ID>` becomes `cardine run <ID>`) |
| PW-24 | 135-140 | Review option order: task override, project default, preset; no silent tightening | G22 | — | one line | 20 | TR1 |
| PW-25 | 142-149 | A spike without review: ANSWERED only if the committed deliverable answers `Question` within `Timebox`, else INCONCLUSIVE | G25 `record_spike_outcome:103` records the declared value and checks nothing | a false ANSWERED satisfies dependents, which then start on a false premise | enforce | 25 | N2 (080) once N1 freezes `deliverables`: A-N2-1 |
| PW-26 | 152-168 | Codex worktree access: root layout, `codex worktree-path`, `codex doctor`, once-per-machine `setup`, repair flow | CLI: `setup`, `codex doctor`, `codex configure` describe themselves | — | moved | 0 | H9 (host setup reference) |
| PW-27 | 170-173 | Consult the command-location table before `execution start` | NONE | none | delete | 0 | RE1 (run works from any directory) |
| PW-28 | 176-183 | `Proceed with` runs `worktree prepare`; the worker starts in that directory and runs `check` first; a mismatch is `WRONG_WORKTREE` | G02, G01 | — | delete | 0 | RE1, RE2 (decision 6) |
| PW-29 | 184-190 | Run `execution start` right after `check`, before analysis, advisor, or implementation | G03 records the transition; the ordering cannot be enforced | none: a skipped start is refused later by G04 and G05 on a `queued` task | delete | 0 | RE1 step 2 starts execution |
| PW-30 | 187-189 | If the record is already archived, skip start, commit closure, run `worktree advance` | G05 (archive move) | — | delete | 0 | SS6 (records stay put); obsolete (CX-07) |
| PW-31 | 191-194 | Absolute paths are runtime values; a handoff records the relative `handoff_worktree` | G02 returns the value; `check_handoff` reads it back (073 T-23) | — | delete | 0 | N3 |
| PW-32 | 196-205 | Resume: `prepare --resume`, `check --resume`, accept `ready-dirty`, read status and diff, confirm sole writer, `start --resume` | G02, G01 `--resume`; sole-writer confirmation is NONE | two writers edit one worktree and overwrite each other | enforce | 0 | RE1 (task lock serializes writers); RE2 step 2 (resume without discarding changes) |
| PW-33 | 211-219 | `Proceed with` authorizes the whole lifecycle; do not ask | G19, G20, G21 allow the commands it needs; the text is the authority | — | one line | 30 | TR1 |
| PW-34 | 221-223 | After APPROVE, `Review` carries the same authority for C6-C10, including the push | G19 allows `git push origin main` for any agent | — | delete | 0 | RE5, RE6 (the engine lands and pushes) |
| PW-35 | 225-230 | The task-branch push is only for `T1_CI`, once per review attempt, never by the reviewer, none without CI | NONE: Claude prompts for `git push origin <branch>` (PRM); the Codex user rule allows any `git push origin` | extra pushes publish work in progress and consume CI | enforce | 0 | RE6 (one plain push per delivered head, with a receipt). **Task 106 (RE6a)**: `integration/ci.py` reads the remote ref, pushes the validated head once with a plain non-force push and records a `ci-push` receipt. |
| PW-36a | 230-231 | Never create, move, or push a tag; never publish a release | Claude: deny `git tag:*`. Codex: NONE for `git tag` (PRM) and the user rule allows `git push origin --tags`. No host denies `gh release create` (PRM) | a release or tag is published | enforce | 20 | no row; input to H9: deny tag and release forms on both hosts (HG-01) |
| PW-36b | 231-232 | Never force, delete, or mirror push | Claude: deny of leading `--force`, `-f`, `--force-with-lease`, `--mirror`, `--delete` (no `-d`, no `+refspec`). Codex: forbidden when the flag is the first or second token. `git push origin main --force` matches the allow rule and no deny rule on Codex (`hosts/codex.py:24-26`, `meridian.rules:26`) | main is rewritten; the file's own comment names the GitHub ruleset as the real guard | enforce | 25 | RE6 (the engine pushes), then H9 removes the agent allow for `git push origin main` (HG-02) |
| PW-36c | 232-233 | No history rewrite: amend of pushed commits, rebase, reset, cherry-pick | Claude: deny `rebase`, `reset --hard`, `cherry-pick`; Codex: forbidden `reset`, `rebase`, `cherry-pick`. `--amend` is in neither list, and `git commit -m` allows it. G06, G07, G08 bind verdicts and evidence to commit IDs, so a rewritten commit is refused | — | one line | 15 | TR1 |
| PW-36d | 233-234 | No deletion of an unmerged branch or force removal of a worktree | Claude: deny `branch -D`, `worktree remove --force`. Codex: PRM. G10 is non-force | — | one line | 10 | TR1 |
| PW-36e | 234 | Never bypass a required independent review | G07 `REVIEW_NOT_APPROVED` (`merge.py:131`, `projections.py:462`) refuses stage. A manual `git merge --ff-only` plus the allowed `git push origin main` never reaches G07 | an unreviewed branch fast-forwards into main when main is its ancestor | enforce | 15 | RE6 and H9 (same as PW-36b); 075 |
| PW-36f | 234-235 | Never resolve a textual conflict | G07 aborts the merge (`merge.py:310`); `git merge` itself is PRM on both hosts | — | one line | 10 | TR1 |
| PW-36g | 235 | No work on another task | G01 binds a worktree to one task; nothing bounds the files an agent edits | edits outside the task land in its branch | enforce | 15 | RE3 (Expected code surface enforcement) |
| PW-37 | 237-241 | `Review: required` is a gate: stop at `REVIEW_REQUIRED` after C3; a fresh reviewer approves; `not_required` proceeds through C10 | G07 `REVIEW_NOT_APPROVED` blocks the harm; no source emits `REVIEW_REQUIRED` (R5) | — | delete | 0 | RE4 (the engine emits the guardrail) |
| PW-38 | 243 | One writer per worktree; `prepare` rejects partial or mismatched state and returns the only branch and path | G02 | — | delete | 0 | RE1 (task lock) |
| PW-39 | 244 | Run `check` before any read from the prepared path; any other checkout is `WRONG_WORKTREE` | G01 | — | delete | 0 | RE1 (the engine resolves the directory; 8 of 15 recorded stops) |
| PW-40 | 245 | The handoff records branch, worktree, commits, validation, integration surface, and full-validation flag; stop writing; leave the worktree clean | `check_handoff` reads the text (073 T-19 to T-23); G04 checks the commit facts; `advance` writes empty surfaces (073 defect 2) | — | delete | 0 | N3; RE3 |
| PW-41 | 246 | Reviewer preflight against the handoff: resolve `handoff_worktree`, `git worktree list`, verify path, branch, HEAD, cleanliness, validated commits | G01, G04 (`delivery_readiness`) prove the same facts from Git | — | delete | 0 | N3 (TPL-08); RE4 |
| PW-42 | 247 | The reviewer never pushes; records `CHANGES_REQUESTED` or `APPROVE` through the command; commits only state, review record, and record projection | G06; G07 `REVIEW_STALE` (`merge.py:137,150`) refuses later non-governance changes | — | delete | 0 | RE4; SS5 and SS6 end the projection |
| PW-43 | 248 | `not_required`: commit evidence, go to closure and integration; never rebase, amend, cherry-pick, or force-push reviewed commits | G07, G08, G11; deny lists as PW-36c | — | delete | 0 | RE5 |
| PW-44 | 249 | Integration is serialized through `integrate stage`, a separate candidate gate, `finalize`, or `abort`; stale evidence is `EVIDENCE_MISMATCH` | G07, G08, G09, G12 | — | delete | 0 | RE5 |
| PW-45 | 251 | Cleanup only through `worktree cleanup`; failure and cancellation keep both checkouts | G10 | — | delete | 0 | RE6 |
| PW-46 | 252 | `Accept <ID>` records `APPROVE --owner`, commits, continues at C6; a manual merge is never permitted | G06 accepts `--owner` from any caller. A manual merge: see PW-36e | an agent passes `--owner` and approves itself | enforce | 20 | 075; RE4 (A-RE4-1) |
| PW-47 | 253 | A forge approval cannot come from the author identity; leave the PR open and report `BLOCKED REVIEW_REQUIRED` | NONE | none: there is no pull-request mode in 1.0 (decision 11) | delete | 0 | RE5 (rejects `pull-request` at configuration) |
| PW-48 | 257-259 | Classify outcomes by the registry's `human_decision` | G15 | — | one line | 25 | TR1 |
| PW-49 | 261-264 | Guardrail: stop on `human_decision: true`, a denied action, or a scope change; `RULE_CONFLICT` and `VALIDATION_RETRY_LIMIT` are guardrails | G15 prints and journals; `RULE_CONFLICT` has no emitter, `VALIDATION_RETRY_LIMIT` is counted by the agent (R5) | an invented stop (issue #15) or an uncounted loop | enforce | 25 | RE3 (engine counts, emits); the name differs from RE3 text (A-RE3-1) |
| PW-50 | 265-268 | Recoverable: run the named recovery in the same turn; never twice; same code again: report | NONE; the registry's `resume` is text the agent follows | an agent loops, or stops on a recoverable state (5 of 7 early stops) | enforce | 0 | RE1, RE2 (`next` command, safe repair inside the step; decision 12) |
| PW-51 | 269-276 | Failing work: rerun once, record an intermittent pass, count the attempt, fix, validate again, stop after N counted failures | NONE: `execution validate` records an exit status and counts nothing | an agent loops forever, or declares exhaustion falsely (issue #15) | enforce | 25 | RE3 (`run.validation` attempts); keep the code `VALIDATION_RETRY_LIMIT` (A-RE3-1) |
| PW-52 | 278-279 | Guidance that no command backs is advice; never stop on its strength | n/a (the definition of advice) | none | one line | 20 | TR1 |
| PW-53 | 281-283 | Never satisfy a gate by writing false state; on a gate that contradicts a rule: `RULE_CONFLICT` | NONE: nothing detects a foreign write; `RULE_CONFLICT` has no emitter | a false state passes (see PW-10) | enforce | 20 | 075; RE1 |
| PW-54 | 285-288 | When a command accepted a state the text forbids, follow the command and write `Rule discrepancies:` in the handoff | NONE | none: a recorded note changes no gate | delete | 0 | N3 (the handoff is free-form); a contradiction is a template defect, fixed in TR1 |
| PW-55 | 292-299 | Closure: commit record and handoff; `task close`; commit closure; `worktree advance` with each result as `--validation-command` and `--validation-exit-code` and `--accepted` | G05, G11 run, but accept the exit codes the agent states (073: 8 code paths) | an agent declares a passing exit code it never obtained | enforce | 0 | RE3 (the engine runs validation and records results); RE5 |
| PW-56 | 301-303 | A named sandbox skip is not a failure only if the test reports it; record `Validation skips:` | NONE | none after RE3 runs validation: the skip appears in the engine's recorded output | delete | 0 | RE3; N3 (TPL-06) |
| PW-57 | 308-314 | Classify the changed surface; documentation-only changes may skip unrelated validation and say so; source changes run everything required plus baseline | NONE: `project show --field validation-scoping` prints the configuration; no gate decides what is skipped (the same rule is repeated at CR-12 and IM-13) | a needed check is skipped and a regression lands | enforce | 25 | RE3 (A-RE3-2: resolve applicability from the frozen `validationScoping`) |
| PW-58 | 316-321 | Before marking done verify acceptance criteria, validation, and baseline; incomplete evidence keeps the task in progress | G11 (C1-C5 evidence); acceptance judgment is the agent's, or the reviewer's when review is required | none beyond the preset's chosen risk: a `lean` task has no reviewer by design | advice | 25 | TR1 |
| PW-59 | 326 | Apply the context policy; use parallel agents only when scopes are independent | NONE | none: cost only | delete | 0 | duplicate of CR-18 |
| RT-01 | AGENTS.md 3 | Read the workflow and language policy before responding or mutating; if missing or contradictory: `BLOCKED WORKFLOW_UNREADABLE` | HOST: the host loads the router; `WORKFLOW_UNREADABLE` as PW-04 | none | one line | 25 | TR1 |
| RT-02 | AGENTS.md 5 | Work only on an assigned task or an authorized read-only request; read the task and `git status --short` first; preserve unrelated changes; select one route; ask when mixed | NONE for choice; G03, G11 act on the task they are given. Staging is allowed by G19 and G20 (`git add`) | unrelated changes are staged or lost | enforce | 25 | RE3 (scope surface bounds what the engine accepts); RE1 |
| RT-03 | AGENTS.md 7-17, CLAUDE.md 11-21 | The seven trigger routes; the same block is generated into both routers | G26 (marker integrity) | — | one line | 40 | TR1 (7 routes become 3) |
| RT-04 | AGENTS.md 19 | Follow `CODE_ORGANIZATION.md` for production source; the routed procedure supplies the rest | NONE | none: a design preference | advice | 15 | TR2 |
| RT-05 | CLAUDE.md 3, 5-9 | CLAUDE.md is generated from AGENTS.md; `Commands` section is filled by the project | NONE (`router.py` generates; CLAUDE.md differs from AGENTS.md in two places) | none | one line | 30 | TR1 |

### `LANGUAGE_POLICY.md` (LP) and the small templates (MS)

The language policy is a frozen file in this repository (`LANGUAGE_POLICY.md`
and its template block) and no row changes its text.

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| LP-01 | 8-10 | Use the persisted conversation language; do not infer or change it from a prompt | REM: the per-turn briefing prints it (G18) | none: a language slip is visible and changes no state, evidence, or history | advice | 45 | none |
| LP-02 | 12-18 | Every repository artifact is English; translate before writing; stop for an amendment if non-English text must be committed | REM (G18); the project can add a validation command | none to gates, state, or history: a violation is a reviewable text defect corrected by a commit | advice | 120 | none |
| MS-01 | README 21-32 | Notes for reproducing the Claude Code setup (model, advisor, effort) | NONE | none | advice | 0 (fill-in text) | none |
| MS-02 | PROJECT_PLAN 5-9, QUEUE 3-8 | The queue and plan status region are generated by `cardine status --write`; do not edit | G23 renders; audit reports drift (SS4) | — | one line | 25 | none (already one line) |
| MS-03 | PROJECT_PLAN 21-36 | Proposals carry no status; the narrative stays free of per-task status | NONE | none: text only | advice | 20 | none |
| MS-04 | TECH_DESIGN, ARCHITECTURE_DECISIONS | Fill-in templates; no rule | n/a | none | advice | 0 | none |
| MS-05 | `.claudeignore`, `.gitignore` | Ignore patterns | HOST: Claude Code reads `.claudeignore` | — | one line | 0 | none |


### Role procedures (IM, RV, RM, LO)

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| IM-01 | IMPLEMENTATION 6-11 | Before `prepare` read only the router set and mutate nothing; `prepare` is the only command allowed before `check` | NONE | none: reading early or running a read-only command first harms nothing | delete | 0 | RE1 (`cardine run` is the first command) |
| IM-02 | 13-16 | Choose one start mode before reading the task; take the ID only from the trigger | G02 takes the ID it is given | none | delete | 0 | RE1 |
| IM-03 | 18-22 | Coordinator-launched worker starts in the supplied directory and runs `check` before any read | G01 | — | delete | 0 | RE1, RE2 |
| IM-04 | 24-39 | Manual start: primary checkout from the first `worktree list` entry; `prepare` without `--worktree-root`; a non-zero result is a stop reported verbatim | G02. The stop contradicts decision 12 for any recoverable code | an agent stops on a state the tool resolves (CX-01) | delete | 0 | RE1, RE2 |
| IM-05 | 41-50 | Resolve the minimum metadata, reconcile a legacy contract, run `execution start` before analysis, advisor, or implementation; review and status never start | G03; reconcile is the CLI's `execution reconcile` | none: a skipped start is refused later by G04 and G05 | delete | 0 | RE1 step 2 |
| IM-06 | 52-58 | A blocked `check` stops all work; if the host cannot write in the prepared directory, return `WRONG_WORKTREE`, name the directory, and never fall back to the primary checkout | G01; G07 refuses a dirty primary | — | delete | 0 | RE1, RE2 |
| IM-07 | 60-70 | `Proceed with` is standing authority for the whole lifecycle, one task-branch push for `T1_CI`, the deny list | repeats PW-33, PW-35, PW-36 | — | delete | 0 | duplicate (DU-01, DU-13) |
| IM-08 | 72-76 | After acceptance and validation, commit, finalize the handoff, run `execution deliver` last, and stop writing | G04 refuses without clean committed HEAD and valid handoff | — | one line | 20 | TR1; RE3 delivers |
| IM-09 | 76-86 | Review required: stop at `REVIEW_REQUIRED`; otherwise go through C10. Twelve codes stop the agent, each reported once, including `ACCEPTANCE_UNMET`, `VALIDATION_FAILED`, `EVIDENCE_INCOMPLETE`, `MAIN_BEHIND_ORIGIN`, `CANDIDATE_VALIDATION_FAILED`, `EVIDENCE_MISMATCH` | G15 registry: those six have `human_decision: false` | an agent stops on recoverable and failing-work states (CX-01) | delete | 0 | RE1, RE2, RE3 (decision 12) |
| IM-10 | 89 | Manual verification: check the rationale first; a missing one or one naming a tier-1 or tier-2 property returns `SCOPE_CHANGE_REQUIRED`; probe the evidence channel before implementing | G14 checks only that the `Manual verification` heading exists (`contract.py:172`). The tier is a judgment | none to state or history: a wasted implementation, no wrong result | advice | 45 | TR2 (blueprint) |
| IM-11 | 91 | Read the host-impact declaration; `NOT_APPLICABLE` needs a rationale; `REQUIRED` needs outcome, profile row, three evidence categories, and fallbacks; missing evidence returns `HOST_IMPACT_DECLARATION_INVALID` | G14 parses record text (`contract.py:195-240`, 073 T-14, T-15). The registry class is `failing-work`; the text says stop | an agent stops on a failing-work code (CX-01) | delete | 0 | N2 (080); N3 (host-impact proofs as an `execution evidence` kind) |
| IM-12 | 93 | If an acceptance criterion cannot be evaluated without discovering an unknown, return `SCOPE_CHANGE_REQUIRED` naming the spike task; do not investigate inside the task | NONE (registry emitter "agent judgment") | none to state or history: scope creep inside a reviewed branch | advice | 30 | TR1 |
| IM-13 | 95-97 | Scope validation to the diff surface; skip the full suite for documentation-only changes | repeats PW-57 | — | delete | 0 | duplicate (DU-04) |
| IM-14 | 99-113 | Run every `Validation` entry only through `execution validate`; running the literal command is not evidence; `execution investigate` before broad research; `ready-check` then `deliver` last | G13 runs only declared literals and writes the exit status; G04 and G11 read it | — | delete | 0 | RE3 (the engine runs validation itself) |
| IM-15 | 115-127 | Phase reads: which document to read at which phase | G24 parses this block to compute read sets (`shared/context.py:_context_phase_reads`) | none | delete | 0 | TR1 (few documents remain); the parser is advisory and moves with them |
| IM-16 | 129-143 | Read ADRs and specifications through `context authority`, `adr show`, `adr list`; never open the whole log or queue; record why a source is opened | G17, G18 refuse large unranged reads | none: cost only | delete | 0 | duplicate of CR-05 (DU-02) |
| RV-01 | REVIEW 8 | After APPROVE, `Review` carries `Proceed with` authority through C6-C10 | repeats PW-34 | — | delete | 0 | duplicate |
| RV-02 | 10-16 | First action: `worktree check` from the prepared directory; a blocked result stops before any read | G01 | — | delete | 0 | RE1, RE4 |
| RV-03 | 17-21 | Read only the handoff; confirm the implementer stopped; a missing field or handoff is `EVIDENCE_INCOMPLETE` | G04 proves committed delivery and clean state; the handoff text is read by T-19 to T-23. "Implementer stopped" has no check | an agent stops on a recoverable code (CX-01) | delete | 0 | N3; RE4 |
| RV-04 | 22-37 | Cross-check the `check` result with the handoff; find exactly one `worktree list` entry; compare branch, full SHA, and a descriptive commit subject; any mismatch is `WRONG_WORKTREE` | G01; the subject comparison is the text gate of 073 TPL-08 | an agent fails a correct handoff because of wording (Contoso, decision 13) | delete | 0 | N3 (TPL-08), 072 |
| RV-05 | 38-44 | Root Git checks in the absolute path; verify top level, branch, HEAD, empty status, commit existence, base ancestry | G01 (path, branch, HEAD, clean); G07 verifies ancestry | — | delete | 0 | RE4 |
| RV-06 | 46-49 | Run `ready-check`; review only a committed `in_review` delivery with a clean worktree; never run `execution start` for a review | G04 | — | one line | 15 | RE4 (`cardine review` hands off only a committed delivery) |
| RV-07 | 51-55 | A failed preflight preserves everything; never switch, move, create, repair, or delete a checkout to pass | G01 refuses; Claude denies `worktree remove --force`; Codex prompts | — | delete | 0 | RE4 |
| RV-08 | 57-62 | Read the task and diff only after preflight; root reads in the verified worktree; review never overlaps the implementer | NONE | none: a reviewer writes nothing, so overlap loses nothing | delete | 0 | RE4 |
| RV-09 | 64 | Record the verdict with the command on the clean HEAD; it writes state, the review heading, and the task `Status` projection; commit those three | G06 binds the verdict to HEAD | — | delete | 0 | RE4; SS5 ends the `Status` projection (CX-05) |
| RV-10 | 65-69 | The validated commit must be an ancestor of HEAD with only lifecycle records between; main may have advanced; reuse, bounded, full, or `EVIDENCE_MISMATCH` | G07, G12 | — | delete | 0 | RE5 (duplicate of IP-03, IP-04) |
| RV-11 | 71-80 | `Proceed with` already authorizes the lifecycle and the attempt's push; the reviewer never pushes the task branch; review is the gate | repeats PW-33, PW-35, PW-36, PW-37 | — | delete | 0 | duplicate (DU-01, DU-13) |
| RV-12 | 82-88 | Thirteen closure codes stop and report once with a resume command, including six non-guardrails | G15: six have `human_decision: false` | an agent stops on recoverable and failing-work states (CX-01) | delete | 0 | RE1, RE2 |
| RV-13 | 91-94 | Candidate validation reads the resolved commands for `REUSE`, `BOUNDED`, `FULL`; a missing declaration stops before staging | G08 (`merge.py:413`), `missing_candidate_validation_commands:462`, G12 | — | delete | 0 | RE5 (configuration drives the engine) |
| RV-14 | 99 | A reviewer edits no implementation file, records the verdict through the command, and commits only the state, record, and review record; it never edits queue or plan | G06 refuses a dirty worktree (`invalid("worktree: allowed clean worktree")`); G07 `REVIEW_STALE` refuses later non-governance changes | — | one line | 15 | RE4 |
| RV-15 | 102-111 | The handoff records branch, worktree, commits, validated base, evidence, and integration surface; stop the implementer; hand over the clean worktree | T-19 to T-23 read the text; G04 checks the commit facts | — | delete | 0 | N3 (duplicate of PW-40) |
| RV-16 | 113-119 | The reviewer never pushes; the implementer makes the next permitted push; `not_required` has no reviewer; owner acceptance continues at C6 | repeats PW-35, PW-46 | — | delete | 0 | duplicate |
| RV-17 | 125-136 | Review runs in a fresh session; only the approval commit uses the project reviewer author printed by `project show --field reviewer-author`; verify with `git log` | `project show` prints a string (`cli.py:545`); nothing checks a commit author (`merge.py`, `closure.py` do not read it); session freshness cannot be observed | the author string is a label anyone types: the control proves nothing, and an implementer approves itself | enforce | 15 | RE4 (provenance recorded by the tool: A-RE4-1); 075 |
| RV-18 | 139-150 | Phase reads for review | G24 | none | delete | 0 | duplicate (DU-03) |
| RV-19 | 152-165 | Bounded context readers | G17, G18 | none | delete | 0 | duplicate (DU-02) |
| RM-01 | REMEDIATION 6-12 | Remediate in the prepared worktree after the reviewer stops; `check` first; never in the primary checkout or a replacement; a mismatch is `WRONG_WORKTREE` | G01 | — | delete | 0 | RE1, RE4 |
| RM-02 | 18-23 | Read the task, review record, and status; confirm `in_progress` with the requested-changes verdict by command results; do not implement new work, reinterpret a finding, or erase evidence | G03 reads state; "reinterpret" has no check | none to state or history: the next review sees the drift | advice | 30 | RE4 (the work request carries the findings) |
| RM-03 | 23-34 | Resolve every unchecked finding; mark each in a new resolution section; rerun validation; `ready-check`; the permitted push; `deliver` last; an authority change returns `SCOPE_CHANGE_REQUIRED` | G04, G06; no gate reads checkboxes | — | delete | 0 | RE4 |
| RM-04 | 37-43 | A finding that needs new authority stays unchecked and returns `SCOPE_CHANGE_REQUIRED`; only an explicit developer authorization restarts it | NONE | none: a stop for a person | advice | 25 | duplicate of LO-14 (DU-08) |
| RM-05 | 45-56 | Phase reads for remediation | G24 | none | delete | 0 | duplicate (DU-03) |
| RM-06 | 58-71 | Bounded context readers | G17, G18 | none | delete | 0 | duplicate (DU-02) |
| LO-01 | LIFECYCLE 6-9 | `Run lifecycle` authorizes an orchestrator to carry one task to `main`, within that task and the gates | NONE | none: `cardine run` is the orchestrator (decision 6) | delete | 0 | RE4, RE7 |
| LO-02 | 11-15 | The orchestrator never implements or reviews; implementer and reviewer are distinct fresh sessions; the reviewer does not see the implementer's reasoning | NONE | none to state or evidence: review quality only, and the verdict is still bound to the commit (G06) | advice | 25 | RE4 (distinct reviewer handoff) |
| LO-03 | 17-33 | Flow diagram; handoff interface is state, record, commits, report, and review record; structured worker messages | NONE | none | delete | 0 | RE1 (the run JSON is the interface) |
| LO-04 | 37-59 | Preconditions: dependency-ready; `prepare` from the primary checkout; pass path and branch to workers; never automatic isolation or `.claude/worktrees`; one `check` first; no concurrent implementer and reviewer in a worktree | G01, G02; concurrency NONE (reviewer writes nothing) | — | delete | 0 | RE1, RE4 |
| LO-05 | 61-68 | Use the commands for status and verdicts; continue while state permits; stop on listed conditions, including validation failure and missing evidence | G06, G25; the list contradicts PW-50 | an agent stops on failing-work states (CX-01) | delete | 0 | RE1, RE3 |
| LO-06 | 70-72 | After two consecutive `CHANGES_REQUESTED`, stop with `REVIEW_LOOP_EXHAUSTED` | NONE: no source emits it; state holds the attempt count | an unbounded review loop spends without limit | enforce | 20 | RE4 (A-RE4-2) |
| LO-07 | 76-97 | Integration authorization; ancestry; reuse, bounded, full; a conflict or gate failure aborts; forge approval | G07, G08, G09, G12. Line 85 sends the reader to `PROJECT_WORKFLOW.md` for a comparison that is in `INTEGRATION_POLICY.md` (CX-02); forge parts do not apply in 1.0 | — | delete | 0 | RE5 |
| LO-08 | 99-104 | Use command-reported state; never load state files; no summarization agent | NONE | none: cost only | delete | 0 | duplicate of CR-12 |
| LO-09 | 107-112 | Candidate validation follows `validation.candidate` | repeats RV-13 | — | delete | 0 | duplicate (DU-16) |
| LO-10 | 114-119 | The implementer and reviewer use one worktree in sequence; integration is defined in `LIFECYCLE_ORCHESTRATION.md` | the block sits in that file and cites itself (CX-03) | — | delete | 0 | TR1 |
| LO-11 | 121-127 | `Accept`: skip the agent review, confirm `in_review`, run `review verdict --owner`, commit, continue at C6 | repeats PW-46 | — | delete | 0 | duplicate |
| LO-12 | 129-161 | Restart a rejected attempt: verify branch, tip, record, a merged design change; in one atomic ref transaction keep `archive/rejected/...` and create `retry/...`; write a restart handoff; never reset, rebase, cherry-pick, or copy | NONE: no command; the agent runs raw ref surgery that neither host allows without a prompt | a wrong ref update loses the rejected tip or rewrites history | enforce | 0 | RE4 (A-RE4-3: `cancel` retains the attempt; the retry is a new task, as PW-08 says reopening is) |

### Context, integration, and worktree documents (CR, IP, WL)

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| CR-01 | CONTEXT 3-4 | Purpose statement | n/a | none | delete | 0 | TR1 |
| CR-02 | 9-11 | Read the router, the task, only its `Authority` entries and the files of its `Expected code surface`; do not scan the repository | G17, G18 refuse large unranged reads only | none: context cost, not integrity | advice | 30 | TR1 |
| CR-03 | 12 | Expand context only when blocked or an acceptance criterion cannot be verified; record the reason in the report | NONE | none | advice | 15 | TR1 |
| CR-04 | 13 | Rely on the per-turn queue briefing instead of opening the queue | G18 prints the briefing from queue rows (`queue-briefing.sh`) | none | delete | 0 | SS7 (briefing on the status service) |
| CR-05 | 14 | Read cited ADRs and specifications with `cardine context authority`, `adr show`, `adr list`; not the whole log | commands exist; G17, G18 refuse large unranged reads | none: cost only | advice | 40 | TR1 (canonical entry for DU-02) |
| CR-06 | 16-23 | The read guard denies a large `Read` without `offset` or `limit` | Codex: G17 for Bash reads only (`cli.py:850`). Claude Code: only the plugin shell hook G18, absent from `cardine setup`, named Meridian, and reading Meridian queue rows to find the active task (`read-guard.sh:97-160`) | none: cost only. The claim "enforced mechanically" holds for Codex and is unverified for a Cardine-only Claude Code install | advice | 15 | H9 (one Python read guard per host); SS7 |
| CR-07 | 27-49 | Isolated exploration: state the question, record it with `execution investigate`, keep the distilled finding; do not bypass authority | `investigate` records and refuses nothing; `--scope` is a self-reported counter that decision 5 removed (`cli.py:450-458`) | none | advice | 35 | RX1 removes the command (CX-08) |
| CR-08 | 51-79 | Minimal read-only status: five steps; a status report is not an audit | NONE | none | delete | 0 | TR1 (`cardine status` is the report) |
| CR-09 | 83-99 | Validation scope (repeats PW-57); a reviewer verifies the same scoping | repeats PW-57 | — | delete | 0 | duplicate (DU-04) |
| CR-10 | 101-112 | Evidence tiers: only a perceptual (tier 3) property justifies manual verification | NONE | none to state or history: rework | moved | 0 | TR2 (blueprint) |
| CR-11 | 114-153 | Execution evidence discipline: reuse session facts; run the profile's literal command with its bound; escalate diagnostics progressively; do not test-and-tune; inspect every hunk; plan manual evidence; reuse unchanged validation in review; `SCOPE_CHANGE_REQUIRED` on a criterion conflict | G13 runs only declared literals; the rest is NONE | none: cost and quality, not integrity | moved | 0 | TR2 (merge into the execution evidence profile as 60 words of advice) |
| CR-12 | 159-176 | Phase reads for status and design; orchestration reading | G24 | none | delete | 0 | duplicate (DU-03) |
| CR-13 | 178-183 | Plans of three bullets or fewer; report only state changes; no parallel agents without independent evidence | NONE | none | advice | 30 | TR1 |
| CR-14 | 185-206 | Context-size policy: the report, the threshold file, the router ceiling, per-role ceilings of 100,000 bytes | G24 reports; `check_repository.py:111-130` enforces a ceiling no role approaches (measured 51,602 bytes at most) | none: the ceiling constrains nothing | enforce | 0 | TR1 (set the ceilings to the section 8 budget in bytes) |
| IP-01 | INTEGRATION 6-12 | Review required: the implementer records the handoff fields and pushes for `T1_CI`; the reviewer uses the same worktree and never pushes | repeats PW-35, PW-40, PW-21 | — | delete | 0 | duplicate (DU-12, DU-13) |
| IP-02 | 14 | After `CHANGES_REQUESTED` the implementer resolves, delivers last, and stops | G04, G06 | — | delete | 0 | RE4 |
| IP-03 | 16-30 | Ancestry checks with `git merge-base` and `git diff --name-only`; a missing or failed check is `EVIDENCE_MISMATCH`; do not fetch, rebase, amend, cherry-pick, or force-push | G07 (`REVIEW_STALE`, `EVIDENCE_MISMATCH`); the deny lists | — | delete | 0 | RE5 |
| IP-04 | 32-47 | One integration lease in the common Git directory; an existing lease is `LEASE_HELD`; compare the advanced `main` with the declared surface; incomplete comparison is `EVIDENCE_MISMATCH` | G07 | an agent stops on another task's lease (decision 14: a task waited for another task's integration lease and stopped) | delete | 0 | RE5; 076 (wait instead of stop) |
| IP-05 | 49-58 | Run `git merge --no-ff --no-commit`; abort on conflict; run `git diff --check` and the declared gate; create the merge commit and push `main` once; remove the worktree and branch; release the lease | G07, G08, G09, G10. It tells the agent to run the merge, while PW-46 and CP-07 forbid a manual merge (CX-09) | — | delete | 0 | RE5, RE6 |
| IP-06 | 60-62 | `not_required` and `Accept` follow the same integration | repeats PW-43, PW-46 | — | delete | 0 | duplicate |
| IP-07 | 64-68 | Reservation, completion, review, and archive mutations stay on the task branch; phase archival waits | G07 refuses conflicts only | — | delete | 0 | SS6, SS4 (CX-05) |
| IP-08 | 73-95 | A reviewer never accepts a bare "tests passed"; use a completed CI run for the exact commit, else validate in scope | `integration/evidence.py:36-86` validates the shape of an evidence record the agent writes (`ci` object); nothing queries CI | a fabricated CI record passes | enforce | 20 | RE3, RE6 (the engine runs validation and polls `gh` for the exact SHA); 075. **Task 106 (RE6a)**: the record verifier is removed; the engine queries the exact repository and SHA through `gh` and caches only a receipt-covered terminal pass. |
| IP-09 | 100-104 | After the `main` push an agent may run `git push origin --delete <task-branch>` without force | Claude denies `git push --delete:*`; Codex forbids `--delete` (`hosts/codex.py:25`): the instruction cannot run on either host | none: it is refused (CX-10) | delete | 0 | RE6 (engine compare-and-delete) |
| WL-01 | WORKTREE 6-13 | After prepare, switch `--project` to the worktree; explicit paths make commands directory independent; every emitted stop line stops work, resume only after an explicit Resume | commands check their location (G01, G03, G05); the second claim contradicts decision 12 | an agent stops on recoverable states and waits for a ritual Resume (CX-01) | delete | 0 | RE1 |
| WL-02 | 15-25 | Table: where each lifecycle command may run and what `--project` names | the commands refuse a wrong location | — | moved | 0 | TR2 (Internal command reference) |
| WL-03 | 30-33, 35-66 | Exit codes 0, 2, 64; the root resolution order; the single-step command list | CLI | — | moved | 0 | TR2 |
| WL-04 | 68-77 | Legacy worktrees are never moved; stage and candidate evidence field lists | CLI | — | moved | 0 | TR2; W10 |
| WL-05 | 79-97 | Commit-less fast-forward recovery with `repair-base` | `worktree repair-base` (`checkout.py:38`); `STALE_WORKTREE_BASE` is a non-guardrail | — | moved | 0 | TR2; RE2 returns the command |
| WL-06 | 99-113 | Queue-section archival rules | `integration/projections.py` archives sections | — | delete | 0 | SS4, SS6 remove phase archival (CX-05) |
| WL-07 | 115-117 | Machine task state adoption with `task state import` | CLI | — | moved | 0 | W10 |
| WL-08 | 119-126, 139-147 | Candidate validation by outcome; `REUSE` proves only governance paths; `BOUNDED`, `FULL` | G08, G12 | — | moved | 0 | TR2 |
| WL-09 | 128-137 | A spike's diff may contain only its record, handoff, ADR, named documentation, changelog fragments, and the evidence ledger | G07 refuses other paths before the lease | — | one line | 0 | TR2 (stated once in the blueprint) |
| WL-10 | 149-150 | `cardine codex worktree-path` is deprecated | CLI | none | delete | 0 | TR2 (CX-08) |
| WL-11 | 152-159 | The absolute worktree path is a runtime value; handoffs use `handoff_worktree` | G02 returns it | — | delete | 0 | N3 (duplicate of PW-31) |

### Task, report, and review templates (TB, CT, EE, RR, CP, AP, OP, CO)

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| TB-01 | BLUEPRINT 4-23 | Header fields; `Class`, `Review`, `Options`, `Manual verification`; omitted options inherit; the CLI freezes the resolved options; a quick task is minimal | G22 reads them once (073 T-01, kept) | — | one line | 60 | TR2; N1 |
| TB-02 | 25-28 | A missing manual-verification rationale, or one naming a tier-1 or tier-2 property, returns `SCOPE_CHANGE_REQUIRED` | repeats IM-10 | — | delete | 0 | duplicate |
| TB-03 | 30-55 | Spike shape: `Question`, `Timebox`, `Deliverable`, `Branch`, `Probe branch`; the deliverable is never production code; the probe branch is never merged or pushed | G07 refuses non-deliverable paths in the spike's diff (WL-09); a pushed probe branch has no check | none to state or history: a pushed throwaway branch | advice | 90 | TR2 |
| TB-04 | 59-65 | `Objective`, and `Authority` required when the resolved option is true | G22, `contract.py:98` | — | one line | 25 | TR2 |
| TB-05 | 67-104 | Host impact: choose `NOT_APPLICABLE` or `REQUIRED`; the profile table and evidence plan | G14 parses it (T-14, T-15) | none | moved | 0 | TR2; N2 |
| TB-06 | 106-115 | Expected code surface: required when the option is true; constrains work either way; omission grants nothing | NONE: `contract.py:98` demands the heading and nothing compares changes with it | work outside the surface lands undetected | enforce | 30 | RE3 (surface enforcement) |
| TB-07 | 117-120 | Acceptance criteria are measurable checkboxes | NONE | none to state or history | advice | 20 | TR2 |
| TB-08 | 122-139 | `Relevant Files`, `Technical Context`, `Out of scope`, `Dependencies` | G23 reads dependencies from the record (T-09) | — | one line | 50 | N1 (dependencies frozen in state) |
| TB-09 | 141-158 | `Validation`: one ID, one complete literal command with its bound; fixed task-scoped paths and no `mktemp`, `$(...)`, or time-based paths; run only through `execution validate` | G13 runs only declared literals; `VALIDATION_ENTRY_FORMAT` checks the format | the fixed-path rule: a permission prompt, nothing else | one line | 55 | TR2; RE3 |
| TB-10 | 160-170 | Record a gap before a diagnostic, capture, or expansion with `execution evidence`; `execution investigate` before broad exploration | CLI records; nothing refuses a missing record; the kinds are the counters decision 5 removed | none | delete | 0 | RX1 (CX-08) |
| TB-11 | 172-180 | Generated `Execution contract — resolved` block; do not edit | T-05 compares the literal (fixed by task 077) | — | delete | 0 | N1 (the snapshot replaces the generated block) |
| TB-12 | 182-194 | Optional research handoff after an investigation | NONE | none | delete | 0 | TR2 |
| TB-13 | 196-200 | Completion steps: `ready-check`, `deliver` last, or `task close`; spike outcome with `task outcome` | G04, G05, G25 | — | delete | 0 | RE3, RE4 (steps of `cardine run`) |
| CT-01 | COMPLETION 3-5 | Write a short handoff after validation at the resolved location; make every deviation explicit | G04 checks the file exists (a Git fact) | — | advice | 25 | N3 (free-form) |
| CT-02 | 7-12, 36-42 | Report outline: `Files changed`, `Candidate validation declaration`, `Validation`, `Validation skips`, `Manual verification`, `Acceptance criteria`, `Isolated exploration`, `Rule discrepancies`, `Blockers/deviations` | `check_handoff` reads these labels (T-19, T-20, T-21; TPL-01, TPL-02, TPL-06, TPL-07) | an agent fails a correct report for wording | delete | 0 | N3 |
| CT-03 | 13-35 | `task-worktree-handoff` block: branch, worktree, three commit fields, integration requirement, declared surface, descriptive forms | T-22, T-23 (TPL-03, TPL-04) | an agent fails on a commit phrase (Contoso, decision 13) | delete | 0 | 072, N3 |
| CT-04 | 45-52 | After a handoff-only correction rerun `execution deliver`, which creates a `Deliver <ID> for review` commit | G04 creates the commit (`commands.py:70,84`) | — | delete | 0 | N3 (TPL-05: the tool writes it) |
| CT-05 | 54 | Do not claim completion when validation fails or a criterion is unresolved; reviews keep the same fields | G11 refuses missing validation evidence; criterion judgment is the agent's | none beyond the preset's risk | advice | 25 | TR2 |
| CT-06 | 56-58 | A named sandbox skip is not a failure; record `Validation skips:` | repeats PW-56 | — | delete | 0 | duplicate |
| CT-07 | 60-66 | Manual verification record: screenshot path, view, result | NONE | none to state or history | advice | 30 | TR2 (DU-06) |
| CT-08 | 68-75 | Report validation as falsifiable evidence: command and exit status, or the CI run | repeats IP-08 | — | delete | 0 | duplicate (DU-07) |
| EE-01 | EVIDENCE 7-11 | Reuse session facts; locate a large-file range first (default 400 lines) | G17, G18 | none | delete | 0 | duplicate of CR-06 |
| EE-02 | 12-15 | Record broad exploration with `execution investigate` | see CR-07 | none | delete | 0 | RX1 |
| EE-03 | 17-32 | Run required checks with `set -o pipefail; cmd 2>&1 \| tail -n 200`; record the literal command, exit status, and final lines; foreground long commands, timeout up to 600 s | G13 runs the declared literal and records the exit status | — | delete | 0 | RE3 (the engine runs and bounds output) |
| EE-04 | 34-55 | Long commands: wait once for the expected duration; Codex `yield_time_ms` and `wait` details (observed on one version); module tests during work, the full suite once at the end | NONE | none: cost only | advice | 40 | H9 (host facts leave the template) |
| EE-05 | 57-75 | Diagnose progressively; inspect every changed hunk; prefer deterministic evidence; faster mode only if evidence is kept | NONE | none | advice | 30 | TR2 |
| RR-01 | REVIEW RECORD 4-9 | One review record per required-review task at the resolved location; the command owns headings; findings are actionable and prioritized | G06 writes the heading; gates read state | — | one line | 40 | TR2 |
| RR-02 | 11-34 | Record outline: attempt heading, commits, evidence, findings, resolution | T-25 (`TPL-09`): the command writes the heading | — | one line | 30 | TR2 |
| RR-03 | 36-39 | `P0` and `P1` findings block approval; `P2` only when bounded; no style commentary | NONE: the verdict is chosen by the reviewer; severity is not parsed | none to state or history: review quality | advice | 25 | TR2 |
| RR-04 | 42-48 | Reviewer confirms the manual-verification screenshot independently | NONE | none | advice | 20 | TR2 (DU-06) |
| CP-01 | CODE_REVIEW_PROMPT 7 | Fresh session; `check` first with `--worktree-root`; verify against the handoff; re-derive evidence | repeats RV-02, RV-04 | — | delete | 0 | duplicate |
| CP-02 | 9-12 | Treat the workflow as the lock; `WORKFLOW_UNREADABLE` | repeats PW-01, PW-04 | — | delete | 0 | duplicate |
| CP-03 | 14 | Read the listed documents and "confirm `Review: required` and `in_review` in the task record" | the record is read, not the state (073 T-13, T-14) | an agent decides review policy from prose (Contoso: integration read state, the transition read the record) | delete | 0 | N2 (CX-06) |
| CP-04 | 16 | Review scope; verify the manual-verification rationale; CI-first evidence; findings with priority and file and line; no style | repeats IP-08, RR-03 | — | advice | 40 | TR2 |
| CP-05 | 18 | A `## Project review checklist` section after the block is additional scope | NONE | none: project-owned | advice | 20 | TR2 |
| CP-06 | 20-24 | Return a verdict through the command; commit three outputs; author override; never push, never edit the queue; use `stage`, `finalize`, `abort`, `cleanup`; never touch the lease or merge directly | repeats RV-14, RV-17, PW-36 | — | delete | 0 | duplicate (DU-11) |
| CP-07 | 26 | Keep the final review report within ten lines | NONE | none | advice | 10 | TR2 |
| AP-01 | AUDIT 4 | The audit modifies nothing | NONE | none: the audit prompt itself | advice | 15 | TR2 |
| AP-02 | 9-28 | Thirteen items of process conformance, project-specific checks, and an output format. Items 6, 10, and 12 describe queue-based dependencies, projections, and applied status that SS4 to SS6 remove | `cardine audit` checks part of it (`cli.py:157`) | none: read-only | moved | 0 | TR2 (run `cardine audit` first; the prompt keeps what it cannot check; CX-05) |
| OP-01 | OPERATOR 3-17 | The cookbook is non-normative; one workflow per chat; implementation and required review in separate chats | NONE | none | advice | 40 | TR2 |
| OP-02 | 19-63 | Prompts 1 and 1a: report status and align tech design | NONE | none | delete | 0 | TR1 (`cardine status`) |
| OP-03 | 65-98 | Prompt 2: design a change, decompose a milestone | NONE | none | moved | 0 | TR2 (150 words) |
| OP-04 | 100-116, 220-231 | Prompts 3 and 10: analyse a result; answer a repository question | NONE | none | delete | 0 | TR2 |
| OP-05 | 118-179 | Prompts 4 to 6a: the five triggers `Proceed with`, `Run lifecycle`, `Review`, `Accept`, `Address review` | repeats RT-03, PW-23 | — | delete | 0 | duplicate |
| OP-06 | 181-188 | Prompt 7: run the audit | repeats AP-01 | — | delete | 0 | duplicate |
| OP-07 | 190-201 | Prompt 8: check an upgrade without running `upgrade --apply`, `adopt`, or `finalize-adoption` | `adopt` does not exist (R4); `upgrade --check` does | none | delete | 0 | TR2 (CX-08) |
| OP-08 | 203-218 | Prompt 9: correct one documentation inconsistency | NONE | none | moved | 0 | TR2 |
| OP-09 | 233-243 | Short forms, including "Report the current SDD handoff state" | names a mode decision 3 removed (CX-12) | none | delete | 0 | TR2 |
| OP-10 | 245-252 | A task starts only when its dependencies are `done` and the developer assigns it; a required review needs a separate chat; never edit a status by hand | G14 `check_dependencies` (`preflight.py:174`) reads the record (T-09); the rest NONE | — | one line | 25 | N1 (dependencies from state); RE1 |
| CO-01 | ORGANIZATION 6 | The policy is subordinate to the router, ADRs, and the task; it never widens scope | NONE | none | advice | 20 | TR2 |
| CO-02 | 8-18 | One owning module per rule; cohesive responsibility; no `utils` or `common` dumping grounds; layers do not depend upward | NONE | none to Cardine's lifecycle: a design preference a reviewer checks | advice | 90 | TR2 |
| CO-03 | 20-22 | The project records its module map in its architecture documentation or after the block | NONE | none | advice | 25 | TR2 |
| CO-04 | 24-31 | Root files hold no behavior; narrowest visibility; a root re-export is public API and changes only when the task authorizes it | NONE | none to Cardine's lifecycle; a public API change is caught by the project's tests and review | advice | 70 | TR2 |
| CO-05 | 33-39 | Tests live with the module; shared fixtures have one owner; moving tests keeps every case | NONE | none | advice | 60 | TR2 |
| CO-06 | 41-49 | Name the owning module in the plan; separate behavior from structural changes; do not relocate unrelated modules; stop and report a missing architectural decision | NONE for the first three; the stop is a guardrail the agent raises | none | advice | 95 | TR2 |


### Host assets that setup installs and the plugin delivers (HX)

These are not in the 21,367-word template set, so `Keep` is 0 and their words
are not in the word budget. They are the rules the host itself applies,
and the skills and commands an agent loads. Work item 9 rebuilds them under
Cardine names, and no row plans it; each finding is recorded as input to that
item and does not plan it. Where a claim concerns what a host does with a rule,
it is read from the rule file and the host's documented prefix semantics (the
file's own comments at `meridian.rules:10-18,45` and `hosts/codex.py:23-26`);
no host was run.

| ID | Lines | Rule | Enforcement | Harm | Action | Keep | Destination |
|----|-------|------|-------------|------|--------|-----:|-------------|
| HX-01 | `meridian.rules` 22-28 | Allow routine Git, including `git push origin main`, `git merge --ff-only`, `git switch`, `git commit -m`, `git add`; prompt on `worktree add`, `remove`, `prune` | G20 | an agent pushes `main` or fast-forwards a branch into it without reaching `integrate stage` (PW-36b, PW-36e) | enforce | 0 | RE6 then H9: the engine pushes, so the agent allow for `git push origin main` and `merge --ff-only` goes (HG-02) |
| HX-02 | 34-44, 59 | Allow read-only and lifecycle commands, written for the `meridian` binary (`context`, `locations`, `adr`, `budget`, `audit`, `codex`, `worktree`, `execution`) | G20 allows `meridian ...`; every `cardine ...` command prompts. `budget` was removed by decision 5 | in an unattended Cardine run each lifecycle command waits for a person, a stop the tool causes (decision 14 rule 3). The file also allows nothing the user-rules block (HX-04) does not (CX-11) | enforce | 0 | H9: generate one rules file from the Stable command surface, under a Cardine name |
| HX-03 | 55-58 | Allow `python3 scripts/check_repository.py` and `python3 -m unittest discover -s tests` | G20 | none: these are this repository's commands shipped to every consumer (CX-11); a consumer's baseline lives in `.cardine/project.json` | delete | 0 | H9 |
| HX-04 | `hosts/codex.py` 23-56 | The Codex user-rules block: allow `git push origin` with any arguments but forbid force, delete, and mirror flags directly after `push` or `origin`; allow `cardine execution`, `task`, `review`, `worktree`; allow `gh` reads, `git fetch`, `git rm` | G21 | any agent runs `cardine review verdict APPROVE --owner` with no prompt and approves itself (PW-46); `git push origin --tags` and `git push origin main --force` pass (HG-01, HG-02) | enforce | 0 | RE4 then H9: owner acceptance leaves the allow list; deny tag and refspec forms |
| HX-05 | `meridian.rules` 62-64; `claude.py` 64-76 | Deny force, delete, mirror pushes, rebase, `reset`, `cherry-pick`, `branch -D`, `worktree remove --force`, `git tag` (Claude) | G19, G20, G21, leading tokens only | a reworded or reordered command passes; the Claude list lacks `-d`, `+refspec`, `--amend`, `gh release create`, and `git update-ref`; Codex lacks `git tag` | enforce | 0 | H9 (HG-01, HG-02) |
| HX-06 | `claude.py` 13-60 | The Claude allow list: 45 entries, including `git commit -m:*` (which matches `--amend`), `git switch:*`, `git add:*`, `git push origin main`, `git merge --ff-only:*`, `cardine worktree` and `execution` commands. It lacks `cardine run`, `status`, `review`, `task` | G19 | a Stable command prompts on Claude Code, and the unattended run waits for a person | enforce | 0 | H9: derive the allow list from the Stable surface; drop the push and merge entries once RE6 lands |
| HX-07 | `.codex/hooks.json` | Run the read guard on Bash and the stop audit on Stop | G17 (Bash reads only), G16 (journals, never blocks) | none: both are advisory; there is no per-turn briefing on Codex | one line | 0 | H9 |
| HX-08 | `hooks/hooks.json`, `queue-briefing.sh`, `read-guard.sh`, `stop-audit.sh` | The Claude plugin prints the briefing each turn, guards large `Read` calls, and journals unbacked stops | G18. The scripts call `bin/meridian`, parse `tasks/QUEUE.md` rows (`[/]` checkbox rows and `\| Order \| ID \|` tables, `read-guard.sh:128-150`), and print `[Meridian ...]` headings. After SS4 the queue is generated with a different shape, and after SS7 the briefing reads the status service | the briefing and the active-task exemption can report a wrong or empty state (decision 6, work item 6 regression) | enforce | 0 | SS7 for the briefing; H9 for one Python implementation per hook (decision 7) |
| HX-09 | `skills/meridian-lean-delivery/SKILL.md` 6-10 | Use the Lean skill for `LEAN_DELIVERY` projects, not for `GOVERNED_SDD` | NONE: skill text; the single lifecycle has no mode marker | none to state or history: the skill chooses a mode decision 3 removed | delete | 0 | H9 |
| HX-10 | lean skill 12-17 | Read the language policy, workflow, and router; the workflow is the mode lock; local rules override global ones; unreadable authority: `BLOCKED` without mutation | repeats PW-01, PW-02, PW-04 | — | delete | 0 | H9 (DU-01) |
| HX-11 | lean skill 19-24 | States `[ ]`, `[/]`, `[x]` in `tasks/QUEUE.md`; only the assigned task; verify and mark `[x]`; keep a failing task `[/]` and unarchived | NONE: no gate reads checkboxes; the state file does (G25) | an agent edits checkbox statuses and archives that the single lifecycle removed (CX-05, CX-12) | delete | 0 | H9 (a skill around `cardine run`) |
| HX-12 | lean skill 26-30 | Proportional scope; a quick task only when small and reversible; follow project Git conventions; a review is read-only unless a fix is authorized | repeats PW-06, RV-14 | — | delete | 0 | H9 (DU) |
| HX-13 | lean skill 32-37 | Ask the developer for `opaque` or `milestone`, never choose, pass it to `meridian setup --apply --task-identity` | the `--task-identity` flag records it (`cli.py:195-199`); repeats HX-33 | — | delete | 0 | H9 |
| HX-14 | lean skill 39 | After validation commit the record and handoff, run `meridian task close`, commit closure; if the record is archived and the state DONE, skip start and run `worktree advance` | G05; the archive special case is obsolete after SS6 | — | delete | 0 | RE1, RE3 (CX-07) |
| HX-15 | lean skill 41-43 | Consult the command-location table before `execution start` | NONE | none | delete | 0 | RE1 |
| HX-16 | lean skill 45-54 | A Lean start "adds no IN_PROGRESS to machine state" and preserves worktree-derived progress | G03 records `queued -> in_progress` for either preset (PW-29) | an agent expects a state that G03 writes (CX-14) | delete | 0 | RE1 |
| HX-17 | `skills/meridian-governed-sdd/SKILL.md` 8-10 | Read the workflow documents, also `docs/CONTEXT_BUDGET_POLICY.md` and the execution evidence profile, before acting | repeats PW-01; `CONTEXT_BUDGET_POLICY.md` is not in the template set (CX-15) | none | delete | 0 | H9 |
| HX-18 | governed skill 12-18 | The workflow is a mode marker; Lean actions are forbidden; `$MERIDIAN_ROOT` names the template source, and if unset stop and ask the user for the path | NONE; the product reads `CARDINE_ROOT` (`cli.py:95`, `setup.py:233`) | an agent stops to ask for a path the product no longer uses (CX-12, CX-15) | delete | 0 | H9 |
| HX-19 | governed skill 22 | Bootstrap: choose identity, copy the governed overlay, `lock --mode governed-sdd`, then `setup --apply --task-identity` after consent | `lock --mode` accepts only `single` (`cli.py:135`): the instructed command is refused | the bootstrap fails on its second command (CX-15) | delete | 0 | H9 |
| HX-20 | governed skill 23 | Tech design: ADRs first, atomic tasks with explicit fields; read `.meridian/task-identity.json`; milestone IDs from `task identity next` | G22 (`task new`); the identity declaration moved to `.cardine/project.json` | an agent reads a file the product no longer writes (CX-15) | delete | 0 | H9 (call `cardine task new`, task 066) |
| HX-21 | governed skill 24-25 | Implement only the requested task; confirm the mode lock before a branch; `Run lifecycle` follows `LIFECYCLE_ORCHESTRATION.md` | repeats RT-02, LO-01 | — | delete | 0 | RE4 (DU) |
| HX-22 | governed skill 26 | Check an upgrade before applying; apply only a conflict-free plan; never hand-copy prompts or edit baselines | `upgrade` applies nothing on a conflict; G26 detects edits | — | delete | 0 | H9 (repeats HX-45) |
| HX-23 | governed skill 27 | Project conversion is unavailable until work item 10 | n/a | none | delete | 0 | W10 |
| HX-24 | governed skill 28-29 | Review with `CODE_REVIEW_PROMPT.md`; record `CHANGES_REQUESTED` and commit only the review-handoff files; owner acceptance follows `docs/workflows/LIFECYCLE.md` | repeats RV-14, PW-46; `docs/workflows/LIFECYCLE.md` is not in the template set (CX-15) | — | delete | 0 | H9 (DU-11) |
| HX-25 | governed skill 30-32 | Audit is a read-only comparison; keep domain architecture in the project, not in the generic assets | NONE | none | delete | 0 | H9 (repeats AP-01, CO-03) |
| HX-26 | governed skill 36 | Apply the context budget policy and evidence profile; start with the task; run the profile's literal commands | repeats CR-02, CR-11 | — | delete | 0 | H9 (DU) |
| HX-27 | governed skill 38-42 | Spike branch roles: the deliverable on the canonical branch, a throwaway probe branch never merged or pushed | repeats TB-03 | — | delete | 0 | H9 (DU) |
| HX-28 | governed skill 44 | State changes and verdicts only through commands; never edit by hand; legacy adoption with `task state import` | repeats PW-10, PW-12, RV-09 | — | delete | 0 | H9 (DU-14) |
| HX-29 | governed skill 46-48 | Consult the command-location table | NONE | none | delete | 0 | RE1 |
| HX-30 | governed skill 50-65 | Execution boundaries: reconcile, start, deliver last, stop writing | repeats IM-05, IM-08 | — | delete | 0 | RE1, RE3 |
| HX-31 | `skills/meridian-lean-delivery-claude-code/SKILL.md` 8-50 | The Claude Code counterpart of HX-09 to HX-16 with `CLAUDE.md` in place of `AGENTS.md`: ranges 8-11, 13-19, 21-27, 29-33, 35, 37-39, 41-50 | as HX-09 to HX-16 | as HX-09 to HX-16 | delete | 0 | H9 (duplicate; one skill per host around `cardine run`) |
| HX-32 | `skills/meridian-governed-sdd-claude-code/SKILL.md` 8-65 | The Claude Code counterpart of HX-17 to HX-30: ranges 8-17, 19-31, 33-35, 37-41, 43, 45-47, 49-65. Lines 12-17 bootstrap through `/meridian-init` with mode `governed-sdd` and `templates/workflows/governed-sdd/`, which no longer exist; line 28 names a `READY_FOR_...` status | as HX-17 to HX-30 | an agent follows a mode, a template directory, and a status that are gone (CX-12, CX-15) | delete | 0 | H9 (duplicate) |
| HX-33 | `commands/meridian-init.md` 5-32 | Ask for project name, preset, task-identity mode (no default), validation commands, and conversation language; the repository language is always English | the answers are written to `.cardine/project.json`, which the CLI validates on every read (`schemas/project-v1.schema.json`) | none to state or history: the choice is recorded in the configuration and editable | advice | 0 | H9 |
| HX-34 | init 34-39 | Copy every file of `templates/single/`; merge `README.md`, `.gitignore`, `.claudeignore`; never overwrite a workflow document without showing its diff and getting confirmation | NONE: the agent copies files by hand; the host prompts for writes only where its permission mode does | a customized workflow document is overwritten | enforce | 0 | H9: a CLI command copies the set and refuses to overwrite (no row) |
| HX-35 | init 41-58 | Write `.cardine/project.json` from the answers: preset, identity, validation commands, baseline, candidate outcomes, `ci` | the CLI validates it on read; a malformed file is refused | — | one line | 0 | H9 |
| HX-36 | init 60-66 | Replace `[Project Name]` and `[Data]`; create `tasks/done/`; fill `CLAUDE.md` commands | NONE. The templates use `[Date]`, and SS6 stops using `tasks/done/` | an empty archive directory and a placeholder that matches nothing (CX-15) | delete | 0 | H9; SS6 |
| HX-37 | init 68-90 | Run `cardine lock` and `setup --check`; run `setup --apply` only after explicit confirmation; never edit user or Codex configuration implicitly | `setup --apply` prompts on both hosts (it is in no allow list) | — | one line | 0 | H9 |
| HX-38 | init 92-95 | Confirm; point to `/meridian-task` | NONE | none | delete | 0 | H9 |
| HX-39 | `commands/meridian-task.md` 7-23 | Workflow-mode gate: read `PROJECT_WORKFLOW.md`; `GOVERNED_SDD` and `LEAN_DELIVERY` take different task steps | NONE; `scripts/check_repository.py:160-175` requires `GOVERNED_SDD` and `BLOCKED` in this file (CX-13) | an agent follows a mode that decision 3 removed (CX-12) | delete | 0 | H9 |
| HX-40 | task 27-43 | Read `.meridian/task-identity.json`, derive the next ID from files in `tasks/`, or run `task identity next` for milestone mode | `task identity next` exists (`cli.py:368`); the file path is the pre-1.0 location | the agent derives an ID by listing files instead of the resolver (CX-15) | delete | 0 | H9 (call `cardine task new`, task 066) |
| HX-41 | task 45-57 | Gather title, category, priority, and objective; create the record by hand from the blueprint | `cardine task new` creates record and state together (G22); a hand-made record has no state and every lifecycle command refuses it | — | delete | 0 | H9 |
| HX-42 | task 59-61 | Add a row to the "Active Queue" of `tasks/QUEUE.md` and to "SECTION 2 — BACKLOG" of `PROJECT_PLAN.md` by hand | G23 generates both (SS4); the plan template no longer has that section | an agent edits generated views (CX-05) | delete | 0 | SS4; H9 |
| HX-43 | task 63-66 | Delegate with `claude "$(cat tasks/NNN-kebab-title.md)"` | NONE | the delegated session starts in the primary checkout with no `Proceed with`, worktree, or state; its edits fail only at `integrate stage` (`PRIMARY_DIRTY`) | enforce | 0 | RE1 (`cardine run` is the launch); H9 |
| HX-44 | `commands/meridian-audit.md` 5-37 | Run `meridian audit --mode governed-sdd`; read PASS, FAIL, SKIP; the command checks capability markers only | G26; `audit --mode` accepts only `single` (`cli.py:164`) | the instructed command is refused (CX-15) | delete | 0 | H9 |
| HX-45 | `commands/meridian-upgrade.md` 5-28 | Check an upgrade; apply only when there is no conflict and the developer authorizes; never resolve markers or edit baselines | `upgrade` applies nothing on a conflict; G26 | — | one line | 0 | H9 |
| HX-46 | upgrade 30-37 | When `docs/workflows/ENTRY_ROUTER.md` exists, `AGENTS.md` and `CLAUDE.md` are derived outputs | the router file and its generator were removed by work item 4 | none: text for a file the set no longer has (CX-15) | delete | 0 | H9 |
| HX-47 | upgrade 39-57 | `--owner-reconciled` registers a baseline without checking files; use it only after reconciling by hand, never to skip that | CLI flag; `upgrade --apply` prompts on both hosts (PRM) | — | one line | 0 | H9 |
| HX-48 | `commands/meridian-adopt.md` 5-7 | Conversion is unavailable until work item 10 | n/a | none | one line | 0 | W10 rebuilds `adopt` |
| HX-49 | `src/cardine/hosts/briefing.py` 23-30 | Print the configured preset above the hook payload and drop the legacy queue headings | `render_briefing` | — | one line | 0 | SS7 (070) |


## Rules `cardine run` makes unnecessary

`cardine run` returns the next action as JSON, resolves the primary checkout and
the task worktree, and returns only commands that run unchanged (decision 6,
`docs/RUN_ENGINE_PLAN.md`). The 55 `delete` entries below name an engine row;
the other `delete` entries are duplicates, obsolete after SS4 to SS6, retired
with the text gates (N3), or host skills that work item 9 rebuilds.

| Engine row | Entries the engine makes unnecessary | Why |
|------------|--------------------------------------|-----|
| RE1 (resolution, output, writer lock) | PW-27, PW-29, PW-38, PW-39, IM-01, IM-02, IM-05, LO-03, WL-01, HX-15, HX-16, HX-29 | location, order of commands, and one writer are resolved by the engine; 8 of the 15 recorded stops are `WRONG_WORKTREE` |
| RE1, RE2 (recoverable states) | PW-28, IM-03, IM-04, IM-06, RV-12 | `prepare`, `check`, and `start` are step 2; the stop lists name recoverable codes |
| RE1, RE2, RE3 | IM-09 | stop lists plus delivery |
| RE1, RE3 | LO-05, HX-14, HX-30 | continuing while state permits, validation failure as iteration, and the closure and delivery sequence |
| RE1, RE4 | RV-02, RM-01, LO-04 | the review and remediation worker receive the directory in `work.worktree` |
| RE3 (validation, retry, surface) | PW-40, PW-56, IM-14, EE-03 | the engine runs validation, bounds output, records skips and results |
| RE3, RE4 | TB-13 | completion steps are engine steps |
| RE4 (review routing, cancel, abort) | PW-18, PW-22, PW-37, PW-41, PW-42, RV-03, RV-05, RV-07, RV-08, RV-09, RM-03, IP-02, HX-21 | roles, reviewer preflight, verdict commits, and requested changes are work requests |
| RE4, RE7 | LO-01 | `Run lifecycle` is `cardine run` |
| RE5 (direct landing) | PW-43, PW-44, PW-47, RV-10, RV-13, LO-07, IP-03, IP-04 | stage, candidate, finalize, abort, and the forge parts that 1.0 rejects |
| RE5, RE6 | PW-34, IP-05 | merge and push by the engine |
| RE6 (push, CI, cleanup) | PW-45, IP-09 | cleanup and the compare-and-delete of the remote task branch |

## Contradictions, duplicates, and obsolete references

### Contradictions between rules, and between rules and the code

| ID | Where | What conflicts | Destination |
|----|-------|----------------|-------------|
| CX-01 | IM-04, IM-09, IM-11, RV-03, RV-12, LO-05, WL-01 | Seven passages tell the agent to stop on codes whose registry entry has `human_decision: false` (`EVIDENCE_INCOMPLETE`, `EVIDENCE_MISMATCH`, `MAIN_BEHIND_ORIGIN`, `VALIDATION_FAILED`, `ACCEPTANCE_UNMET`, `CANDIDATE_VALIDATION_FAILED`, `HOST_IMPACT_DECLARATION_INVALID`) and WL-01 makes Resume a ritual. PW-48 to PW-51 and decisions 12 and 14 say the opposite. This is the cause of 5 of the 7 early Cardine stops | RE1, RE2, RE3 |
| CX-02 | LO-07 (line 85) | Sends the reader to `PROJECT_WORKFLOW.md` for the material-interaction comparison; that comparison is at `INTEGRATION_POLICY.md:38-47` | RE5; TR2 |
| CX-03 | LO-10 (lines 116-118) | Defines the integration transaction by pointing to the file that contains the sentence | TR1 |
| CX-04 | PW-07 (line 55) | Lists the queue as an authority for execution scope, dependencies, and review policy; decision 4 and SS4 make it a generated view and the state file the source | TR1 |
| CX-05 | PW-13, PW-30, RV-09, IP-07, WL-06, AP-02, HX-11, HX-14, HX-42 | Describe `Status:` projections, queue and plan status applied by `integrate stage`, archive moves, and phase archival that SS4 to SS6 remove | SS6 and SS4 remove the code; A-SS7-1 removes the sentences; TR1, TR2 |
| CX-06 | PW-19, CP-03 | An agent is told to record status in the record, or to confirm review policy and `in_review` in the record, while PW-10 makes the state file the only authority; Contoso failed on exactly this | N2 (080); TR1 |
| CX-07 | PW-29, PW-30 | A resume special case keyed to an archived record, which SS6 stops producing | SS6 |
| CX-08 | OP-07, `meridian.rules` 35-37, IM-14, CR-07, TB-10, EE-02, PW-26, WL-10 | Name commands that are gone or retired: `adopt` and `finalize-adoption` (R4 finds `adopt` mechanically), `budget`, the `execution evidence` kinds and `investigate --scope` that decision 5 lists as removed (`cli.py:443-458`, `tasks/recording.py:18,103-135`), and the deprecated `codex worktree-path` | RX1 for the counters; TR2; W10 for `adopt` |
| CX-09 | IP-05 | Tells the agent to run `git merge --no-ff --no-commit`, while PW-46 and CP-06 forbid a manual merge | RE5 |
| CX-10 | IP-09 | Tells the agent to run `git push origin --delete`, which both hosts refuse (HX-05) | RE6 |
| CX-11 | HX-02, HX-03 | The template rules file names `meridian` commands and this repository's own test commands, and duplicates the Codex user-rules block (HX-04) | H9 |
| CX-12 | OP-09, HX-09, HX-11, HX-18, HX-32, HX-39 | A single-lifecycle set still carries Governed SDD and `LEAN_DELIVERY` vocabulary, and `scripts/check_repository.py:160-175` pins `GOVERNED_SDD` in `commands/meridian-task.md` | H9; TR2 |
| CX-13 | PW-04, RT-01, OP-01, HX-39 | `scripts/check_repository.py:150-175` fails unless five files contain `BLOCKED WORKFLOW_UNREADABLE`, the cookbook contains "This non-normative cookbook", and `commands/meridian-task.md` contains `GOVERNED_SDD`. Deleting PW-04 or RT-01 without changing the check fails the repository gate | TR1, TR2 change the check in the same row |
| CX-14 | HX-16, HX-11 against PW-08, PW-29 | The Lean skill says a Lean start adds no `IN_PROGRESS` to machine state and that status is `[ ]`, `[/]`, `[x]`; the template says start records `queued -> in_progress` for either preset and the state file holds the status | H9 |
| CX-15 | HX-17, HX-19, HX-20, HX-24, HX-36, HX-40, HX-44, HX-46 | Stale references: `docs/CONTEXT_BUDGET_POLICY.md`, `docs/workflows/LIFECYCLE.md`, and `docs/workflows/ENTRY_ROUTER.md` are not in the template set; `lock --mode governed-sdd` and `audit --mode governed-sdd` are refused (`cli.py:135,164` accept only `single`); `.meridian/task-identity.json` and `$MERIDIAN_ROOT` are the pre-1.0 names (`.cardine/project.json`, `CARDINE_ROOT`); `/meridian-init` replaces `[Data]` where the templates say `[Date]` | H9 |

### Duplicated rules

`R2` found nine capabilities repeated in several files (2,478 words of managed
block, counting every copy). The rest of the duplication is in prose.

| ID | Rule | Entries | Canonical entry |
|----|------|---------|-----------------|
| DU-01 | Authority of `Proceed with` and the deny list | PW-33 to PW-36, IM-07, RV-11, LO-07, IP-01 | PW-33, PW-36a to PW-36g |
| DU-02 | Bounded context readers (387 words in 3 files) | CR-05, IM-16, RM-06, RV-19 | CR-05 |
| DU-03 | Phase reads (271 words in 4 files) | CR-12, IM-15, RM-05, RV-18 | none: removed with the read-order prose (TR1) |
| DU-04 | Validation scoping (241 words in 3 files, plus CR-09) | PW-57, CR-09, IM-13 | PW-57 |
| DU-05 | Command triggers (112 words, in `AGENTS.md` and `CLAUDE.md`) | RT-03 | RT-03 |
| DU-06 | Manual-verification record (92 words, 2 files) | CT-07, RR-04 | CT-07 |
| DU-07 | CI-verified validation (269 words, 2 files) | IP-08, CT-08 | IP-08 |
| DU-08 | Rejected-attempt restart (323 words, 2 files) | RM-04, LO-12 | LO-12 |
| DU-09 | Review-remediation record (502 words, 2 files) | RR-01, RM-03 | RR-01 |
| DU-10 | Worktree command locations (281 words, 2 files) | PW-27, WL-01 | none: RE1 |
| DU-11 | The reviewer author override | RV-17, CP-06, AP-02 | RV-17 |
| DU-12 | The implementer-to-reviewer handoff | PW-40, RV-15, IP-01, CT-03 | none: N3 |
| DU-13 | The task-branch push for `T1_CI`: 13 mentions in 8 files | PW-35, IM-07, RV-11, RV-16, LO-07, IP-01, RM-03, CT-03 | PW-35 |
| DU-14 | "Never edit a status or verdict by hand": 18 mentions in 13 files | PW-10, RV-09, RV-14, RM-03, TB-13, RR-01, OP-10, and others | PW-10 |
| DU-15 | The list of closure stops | IM-09, RV-12 | none: RE1, RE2 |
| DU-16 | Candidate validation for `REUSE`, `BOUNDED`, `FULL` | RV-13, LO-09, WL-08, IP-05 | WL-08 |

### Host gaps (input to work item 9; no row covers them)

| ID | Gap | Entries |
|----|-----|---------|
| HG-01 | No host denies publishing a release or pushing a tag: Codex has no `git tag` rule and its user rule allows `git push origin --tags`; neither host denies `gh release create` | PW-36a, HX-04, HX-05 |
| HG-02 | The agent may push `main` with the flag after the refspec, and may fast-forward a branch into `main` with the allowed `git merge --ff-only`; the GitHub ruleset is the only guard, named in `hosts/codex.py:24-26` | PW-36b, PW-36e, HX-01, HX-04 |
| HG-03 | The Codex user rules allow `cardine review` for any agent, so `--owner` approval needs no prompt | PW-46, HX-04 |
| HG-04 | The Claude Code read guard, briefing, and stop audit are Meridian-named shell scripts that `cardine setup` does not install and that read Meridian queue rows; their behavior in a Cardine-only install is unverified | CR-06, HX-08 |

### Defects found

1. **Template read sets are misreported.** `cardine context size` prints `MISSING
   cited: docs/AGENTS.md`, `docs/PROJECT_WORKFLOW.md`, and similar for every role
   (R3). `shared/context.py:_context_relative_references` resolves a name cited
   in `docs/workflows/IMPLEMENTATION.md` against that document's directory, so
   root files are reported missing. Destination TR1.
2. **The context ceilings constrain nothing.** `check_repository.py:111-130`
   enforces 100,000 bytes per role; the largest measured read set is 51,602
   bytes (CR-14). Destination TR1.
3. **Seven registered codes have no emitter in `src/` or `scripts/`**:
   `REVIEW_REQUIRED`, `PUSH_REJECTED`, `REVIEW_LOOP_EXHAUSTED`,
   `SCOPE_CHANGE_REQUIRED`, `RULE_CONFLICT`, `VALIDATION_RETRY_LIMIT`, and
   `WORKFLOW_UNREADABLE` (R5). The first three and the retry limit can be
   emitted from facts (PW-37, LO-06, PW-51); the others are judgments a
   person must receive. Destination 076 decides each; this document records the
   rule consequence only.
4. **The `advance` path fabricates two evidence fields.**
   `integration/evidence.py:314` writes `interaction_assessment_complete: true`
   unconditionally and `lifecycle/closure.py:152-156` passes empty dependency
   and surface lists, so PW-40's "declared integration surface" is not real
   input there. This is task 073's defect 2 and is still open at this commit;
   task 073's defect 1 (`required via meridian execution`) was fixed by task 077
   (`contract.py:151`, `TASK_BLUEPRINT.md:180`). Destination N3, RE3, 075.
5. **Repository checks pin template prose** (CX-13). Rewriting the templates
   fails `check_repository.py` unless the checks change in the same row.

## Word budget

Today an agent that is told `Proceed with <ID>` reads 7,220 words before it
starts (router 180, workflow 3,468, language policy 186, implementation
procedure 1,660, context policy 1,726), and 10,367 words by completion. After
work item 8 it needs the next action `cardine run` returns, the task contract,
and a short statement of what is enforced, advice, and denied.

**Proposed budget** (words; one word is about 7.2 bytes, from `PROJECT_WORKFLOW.md`'s
25,032 bytes and 3,468 words):

| Budget | Words | Bytes | Today |
|--------|------:|------:|------:|
| Router + workflow + language policy (every task) | 1,100 | 8,000 | 3,834 |
| Any role's read set at start | 1,400 | 10,000 | 4,432 to 7,220 |
| One role including documents read at later phases | 2,700 | 20,000 | up to 10,367 |
| The whole `templates/single/` set | 5,600 | 40,000 | 21,367 |
| `PROJECT_WORKFLOW.md` alone | 750 | 5,400 | 3,468 |
| Any other single document | 650 | 4,700 | up to 1,726 |

**The actions reach it.** The next table adds, per final file, the `Keep` of its
surviving entries, a frame (headings, markers, and the fill-in skeleton, an
estimate) and the words of `moved` entries after they are condensed into the
file that receives them (an estimate that TR2 fixes). `Keep` figures are the
`Keep` column of the entry tables, summed by the self-check.

| Final file | Today | Σ Keep | Frame | Moved in | Budget |
|------------|------:|-------:|------:|---------:|-------:|
| `AGENTS.md` (RT-01 to RT-04) | 180 | 105 | 15 | 0 | 120 |
| `CLAUDE.md` (RT-01 to RT-05) | 129 | 135 | 15 | 0 | 150 |
| `PROJECT_WORKFLOW.md` (PW) | 3,468 | 690 | 40 | 0 | 730 |
| `LANGUAGE_POLICY.md` (LP, text frozen) | 186 | 165 | 21 | 0 | 186 |
| `docs/workflows/IMPLEMENTATION.md` (IM) | 1,660 | 95 | 20 | 0 | 115 |
| `docs/workflows/REVIEW.md` (RV, absorbing CP and IP) | 1,637 + 686 + 1,048 | 135 | 25 | 0 | 160 |
| `docs/workflows/REMEDIATION.md` (RM) | 598 | 55 | 20 | 0 | 75 |
| `docs/LIFECYCLE_ORCHESTRATION.md` (LO) | 1,463 | 45 | 20 | 0 | 65 |
| `docs/CONTEXT_READING_POLICY.md` (CR) | 1,726 | 165 | 20 | 0 | 185 |
| `tasks/TASK_BLUEPRINT.md` (TB) | 1,320 | 330 | 250 | 60 (CR-10) | 640 |
| `docs/COMPLETION_REPORT_TEMPLATE.md` (CT) | 728 | 80 | 30 | 0 | 110 |
| `docs/EXECUTION_EVIDENCE_PROFILE.md` (EE) | 491 | 70 | 30 | 60 (CR-11) | 160 |
| `docs/REVIEW_RECORD_TEMPLATE.md` (RR) | 345 | 115 | 60 | 0 | 175 |
| `docs/WORKTREE_LIFECYCLE.md` (reference) | 1,561 | 0 | 0 | 340 (WL, PW-12) | 340 |
| `docs/AUDIT_PROMPT_READ_ONLY.md` (AP) | 663 | 15 | 0 | 300 (AP-02) | 315 |
| `docs/OPERATOR_PROMPTS.md` (OP) | 1,637 | 65 | 20 | 210 (OP-03, OP-08) | 295 |
| `docs/CODE_ORGANIZATION.md` (CO) | 608 | 360 | 20 | 0 | 380 |
| `docs/CODE_REVIEW_PROMPT.md`, `docs/INTEGRATION_POLICY.md` | 686 + 1,048 | into REVIEW | | | 0 |
| Fill-in and generated: `README`, `TECH_DESIGN`, `PROJECT_PLAN`, `QUEUE`, `ARCHITECTURE_DECISIONS` | 633 | unchanged | | | 633 |
| Host files `.codex/*`, ignore files (H9 changes them) | 600 | unchanged | | | 600 |
| New host setup reference (PW-26, H9) | 0 | | | 100 | 100 |
| **Total** | **21,367** | | | | **5,534** |

The total is 74% below today and 66 words under the 5,600-word budget. Per role,
the same table gives:

| Role | Documents at start | After | Today | Later phases | After, with later phases | Today, with later phases |
|------|--------------------|------:|------:|--------------|-------------------------:|-------------------------:|
| implementation (`AGENTS.md`) | router, workflow, language policy, IM, CR | 1,336 | 7,220 | CO, TB, EE, CT | 2,626 | 10,367 |
| review | router, workflow, language policy, RV | 1,196 | 5,471 | CO, EE, RR | 1,911 | 6,915 |
| remediation | router, workflow, language policy, RM | 1,111 | 4,432 | CO, EE, LO | 1,716 | 6,994 |
| lifecycle | router, workflow, language policy, LO, RV | 1,261 | 6,934 | none | 1,261 | 6,934 |
| status, design | router, workflow, language policy, CR | 1,221 | 5,560 | none | 1,221 | 5,560 |

The Claude Code route adds 30 words (`CLAUDE.md` is 150 words, not 120). Every
start figure is under the 1,400-word budget with a margin of at least 64 words.
The margin is small by design: TR1 measures the real words, and the static
guard it adds fails above the budget. The 100,000-byte ceilings of
`CONTEXT_READING_POLICY.md:199-206` become the byte column above.

The figures hold only if the enforce rows land. The 31 `enforce` entries become
one-line statements (`Keep` 0 to 30 words each) after their gate exists; until
then a rule that causes harm stays in prose, which is the state rule 1 forbids.
That ordering is why TR1 follows RE6.

## Destinations

A row covers a finding only when its scope text says so. An entry can name
several destinations. Counted from the `Destination` column of the 268 entries
(the self-check script prints them): TR1 40 and TR2 42; RE1 to RE7 120 (RE1 33,
RE2 9, RE3 23, RE4 33, RE5 11, RE6 10, RE7 1); SS4 to SS7 19; N1 to N3 26 and
tasks 072, 080 four; tasks 075 and 076 nine; H9 46; RX1 3; W10 5; task 070 one.

### Existing rows that already cover the finding

| Row | Findings it covers by scope text |
|-----|----------------------------------|
| RE1 | Location independence and a task lock that serializes writers (PW-32, PW-38, PW-39) |
| RE2 | Recoverable states return `next`; a resume without discarding changes (CX-01, PW-32, PW-50) |
| RE3 | Validation attempts and retry, expected-surface enforcement, engine-run validation (PW-36g, PW-51, PW-55, TB-06, EE-03) |
| RE4 | No self-approval, review routing, cancel and abort (PW-21, PW-46, RV-17 by intent; not by mechanism) |
| RE5 | Direct landing only, rejecting `pull-request` (PW-47) |
| RE6 | One push per delivered head, exact-SHA CI, remote compare-and-delete (PW-35, IP-08, IP-09) |
| SS6 | Stable records, `task close` without moving the record (PW-30, CX-07) |

### One-sentence amendments

| ID | Row | Amendment | Why the scope text does not already say it |
|----|-----|-----------|---------------------------------------------|
| A-RE1-1 | RE1 | Receipts also bind the digest of the state file the engine wrote, so a write by anything but the engine is detected; 075 chooses the mechanism | RE1 serializes and receipts the engine's own writes; nothing detects a foreign write (PW-10, PW-53) |
| A-RE3-1 | RE3 | The retry guardrail keeps the registered name `VALIDATION_RETRY_LIMIT` (used by `PROJECT_WORKFLOW.md:264`, `IMPLEMENTATION`, and the registry); do not register `VALIDATION_RETRY_EXHAUSTED` | RE3 and the templates name two codes for one guardrail |
| A-RE3-2 | RE3 | The engine decides which declared commands apply to a diff from the frozen `validationScoping` and records any skip itself | RE3 runs "the resolved task commands plus applicable baseline" but does not say who decides applicability (PW-57) |
| A-RE4-1 | RE4 | A verdict is accepted only for a review the engine issued to a reviewer identity other than the implementer's, and `--owner` is accepted only from a command run by the developer | RE4 forbids self-approval without naming a mechanism, and `review verdict` accepts any caller (G06, RV-17, PW-46) |
| A-RE4-2 | RE4 | The engine emits `REVIEW_LOOP_EXHAUSTED` after two consecutive `CHANGES_REQUESTED` attempts recorded in state | RE4 does not mention the loop limit (LO-06) |
| A-RE4-3 | RE4 | `cancel` keeps the rejected attempt's branch and a restart is a new task; the `archive/rejected` and `retry` ref procedure is deleted | RE4 covers cancel and abort, not restart (LO-12) |
| A-N2-1 | N2 (080) | `task outcome ANSWERED` requires every frozen deliverable path to be changed on the task branch | N1 freezes `deliverables`, but no row uses them to gate the outcome (PW-25) |
| A-SS7-1 | SS7 (070) | The template edit also removes the sentences that say a task branch never edits the queue and that `integrate stage` applies queue status | SS7 documents reading and regeneration; PW-13, WL-06, and IP-07 become false by SS4 to SS6 |
| A-RE7-1 | RE7 | Its documentation covers the product commands only; template prose belongs to TR1 and TR2 | RE7 lists "product command documentation", which a reader could extend to the templates |

### Proposed new rows

None of the following is a queue entry or authorization to start work.

| Row | Title | Size | Scope | Placement |
|-----|-------|------|-------|-----------|
| **RX1** | Remove the self-reported evidence counters decision 5 removed | ~2h | Delete `execution evidence` (`diagnostic`, `captures`, `expansions`) and `investigate --scope` (`cli.py:443-458`, `tasks/recording.py:18,103-135`) with their tests and the template text that asks for them (TB-10, CR-07, EE-02, IM-14). Rule 1 of decision 14 forbids a command the engine makes redundant | After SS7, before RE3 (RE3 refactors `tasks/recording.py` and `tasks/evidence.py`) |
| **TR1** | Rewrite the always-read template set to the budget | ~3h | `AGENTS.md`, `CLAUDE.md`, `PROJECT_WORKFLOW.md`, `docs/workflows/{IMPLEMENTATION,REVIEW,REMEDIATION}.md`, `LIFECYCLE_ORCHESTRATION.md`, `CONTEXT_READING_POLICY.md`; fold `CODE_REVIEW_PROMPT.md` and `INTEGRATION_POLICY.md` into `REVIEW.md`; set the `check_repository.py` ceilings to the budget; update the prose-pinning checks of CX-13; fix defect 1; add a guard that fails above the budget, on a template command missing from the argparse tree (R4), and on a stop listed as a stop whose `human_decision` is false; bump capability versions and the marker baseline | After RE6 (the text points at `run`, `review`, `cancel`, and landing), before RE7 |
| **TR2** | Condense the reference documents | ~3h | `WORKTREE_LIFECYCLE.md`, `TASK_BLUEPRINT.md`, `COMPLETION_REPORT_TEMPLATE.md`, `EXECUTION_EVIDENCE_PROFILE.md`, `REVIEW_RECORD_TEMPLATE.md`, `AUDIT_PROMPT_READ_ONLY.md`, `OPERATOR_PROMPTS.md`, `CODE_ORGANIZATION.md` to the section budget; delete the two folded documents | After TR1 and after N3 (the handoff stops being a gate) |

The host findings (HG-01 to HG-04 and HX-01 to HX-49) belong to work item 9. No
row covers them, and this document does not plan the item.

## Cross-references

- **Task 073, `docs/TEXT_GATE_INVENTORY.md`.** Cited by entry ID: T-01 to T-47
  and TPL-01 to TPL-12 appear in PW-06, PW-31, PW-40, RV-03, RV-04, CT-02 to
  CT-04, and others. This document adds one text-reading surface that 073 did
  not list: `shared/context.py` parses the phase-read and routing blocks of the
  templates (`_context_phase_reads`, line 86) to compute read sets. It is
  advisory and moves with TR1. Rows 072, 078, 079 (N1 part 1), and 080 (N2) are
  cited as destinations only.
- **Task 075, forgery.** PW-10, PW-21, PW-46, PW-53, RV-17, and IP-08 depend on
  what an agent can write. They name 075 and do not choose a defense.
- **Task 076, stops.** PW-04, PW-37, PW-49, PW-50, LO-06, and defect 3 depend on
  which stop codes survive. They name 076 and do not remove a code.

## Self-check

The entry tables are checked by a script that fails on a violation of rule 1:
a row without enforcement and with a stated harm may not be `one line` or
`advice`; an `advice` row with a partial gate and a stated harm fails; an `enforce`
row needs a destination row; `delete` and `moved` rows keep 0 words; and every
other row keeps at least one word. Save the script below as `rule_check.py` outside the repository, then run
`python3 rule_check.py < docs/RULE_ENFORCEMENT_INVENTORY.md`.

```python
import re, sys
ACTIONS = {"enforce", "one line", "advice", "delete", "moved"}
ROWS = re.compile(r"RE[1-7]|SS[4-7]|\bN[1-3]\b|TR[12]|RX1|\bH9\b|\bW10\b|\b0[78][0-9]\b|A-[A-Z0-9]+-\d")
errors, entries = [], []
for line in sys.stdin.read().splitlines():
    if not line.startswith("| "):
        continue
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    if len(cells) == 8 and re.match(r"^[A-Z]{2}-\d+[a-z]?$", cells[0]):
        entries.append(cells)
for eid, lines, rule, enf, harm, action, keep, dest in entries:
    keep = int(keep.split()[0])
    none_enf = enf.startswith(("NONE", "REM", "n/a"))
    harmless = harm.startswith("none") or harm in ("—", "-")
    if action not in ACTIONS: errors.append(f"{eid}: action {action}")
    if none_enf and not harmless and action in {"one line", "advice"}: errors.append(f"{eid}: harm without gate")
    if not none_enf and action == "advice" and not harmless: errors.append(f"{eid}: advice with harm")
    if action == "enforce" and not ROWS.search(dest): errors.append(f"{eid}: no row")
    if action in {"delete", "moved"} and keep: errors.append(f"{eid}: keeps words")
    if action in {"one line", "advice"} and keep == 0 and not eid.startswith(("HX-", "WL-09", "MS-")): errors.append(f"{eid}: keeps none")
import collections
GATE = re.compile(r"\bG\d\d\b|HOST:|CLI|PRM|\.py|`(cardine|execution|task|review|worktree)")
def kind(enf):
    if enf.startswith(("NONE", "REM")): return "none"
    if enf.startswith(("repeats", "as HX")): return "repeats another entry"
    return "gate or host rule named" if GATE.search(enf) else "other"
print(len(entries), "entries;", len(errors), "errors"); [print(e) for e in errors]
print(dict(collections.Counter(e[5] for e in entries)))
print(dict(collections.Counter(kind(e[3]) for e in entries)))
print("enforce:", dict(collections.Counter(kind(e[3]) for e in entries if e[5] == "enforce")))
dests = collections.Counter(t for e in entries for t in re.findall(r"RE[1-7]|SS[4-7]|\bN[1-3]\b|TR[12]|RX1|\bH9\b|\bW10\b|\b0[78][0-9]\b", e[7]))
print(dict(sorted(dests.items())))
print("keep by prefix:", dict(sorted(collections.Counter({k: sum(int(e[6].split()[0]) for e in entries if e[0].startswith(k + "-")) for k in sorted({e[0].split("-")[0] for e in entries})}).items())))
sys.exit(bool(errors))
```

Result on this commit: 268 entries; 0 errors. Action counts: enforce 31, one
line 38, advice 40, delete 145, moved 14. Enforcement cell: a gate or host rule
named for 146 entries, a repeat of another entry's gate for 30, none for 74, and
18 that say `n/a` or name the stop that makes the rule moot. Of the 31 `enforce`
entries, 12 have no gate at all and 19 have a gate with a gap that the entry
names.

## Limits of this inventory

- The entry granularity is one normative clause or paragraph, not one sentence.
  A rule restated in another file has its own entry and points to the canonical
  one (DU table).
- `Keep` words and the frame and moved-in figures are estimates. They show that
  the actions reach the budget with a 64-word margin; TR1 and TR2 fix the real
  figures, and the guard they add enforces the budget.
- Host claims are read from rule files and their comments. No host was run, no
  Codex `execpolicy check` ran, and no probe was made.
- The measured read sets use the AGENTS.md route that `cardine context size`
  selects first.
- Asset words for the skills and commands are counted ("Files and when an
  agent reads them") but are not part of the template budget.

### RE6b disposition (task 107)

G10, PW-45, IP-05 and IP-09 now run through receipt-bound
`integration/cleanup.py`: verified main push, exact remote task-ref compare-delete,
non-force worktree/branch cleanup and lifecycle removal. Every effect rechecks
the actual remote and landed tip. The capability belongs to the lifecycle
engine; it does not authorize an agent to delete remote branches. PW-32's
dirty-resume path additionally requires Resume to be recorded in the verified
preparation receipt. Same-user receipt checks do not install or prove effective
host permissions.

### TR1a disposition (task 110)

The always-read set was rewritten to the budget: the routers, `PROJECT_WORKFLOW.md`,
the implementation, review, and remediation procedures, `LIFECYCLE_ORCHESTRATION.md`,
and `CONTEXT_READING_POLICY.md`. `tests/test_template_entry_actions.py` pins each
entry destined for TR1 to its action (deleted prose leaves no phrase; kept rules are
stated; advice carries its label), and `tests/test_template_word_budget.py` measures
both host routes from explicit file lists.

- `CODE_REVIEW_PROMPT.md` and `INTEGRATION_POLICY.md` are folded into `REVIEW.md`
  (CP-04, CP-05, CP-07, RR-03, IP-08, RV-06, RV-14, RV-17). The files stay until TR2b
  deletes them.
- RT-03 projected three routes; six remain because `Accept <ID>` is a developer-only
  command whose procedure is `LIFECYCLE_ORCHESTRATION.md`, and the status, design,
  and lifecycle read sets resolve their route from the router.
- CR-14 keeps the ceiling table parseable; TR1b sets its values and fixes defects 1
  and 2. The `phase-reads` parser in `shared/context.py` is also TR1b's.
- CR-10 (evidence tiers) moved into `TASK_BLUEPRINT.md` and the remainder of CR-11
  into `EXECUTION_EVIDENCE_PROFILE.md`, so neither is lost before TR2a condenses them.
  OP-02 (prompts 1 and 1a) left `OPERATOR_PROMPTS.md`.
- The reviewer author override (RV-17) is gone: the issued review request
  (`--request-id`) identifies the reviewer. No template claims authenticity beyond the
  plan's trust boundary.
- At this commit `cardine run` returns its own command as `next` for the contract and
  worktree steps of a queued task and does not prepare the worktree itself; the
  templates tell the agent to follow `next` unchanged, as the plan designs, and RE7b
  audits the remaining adapters.
