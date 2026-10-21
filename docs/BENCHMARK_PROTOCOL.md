# Benchmark protocol: Cardine against a minimal competent procedure

Status: protocol decided on 2026-10-22. Nothing has been run. Measured runs
start only on Cardine 0.9.

## 1. Purpose

Adopters need to know when Cardine pays off. This benchmark compares the same
agent on the same tasks in two ways: with Cardine coordinating the lifecycle,
and with a minimal competent procedure and no Cardine. It reports cost, time,
supervision, and reliability. It must be able to show a disadvantage, or no
benefit, as readily as an advantage. Its results feed the README positioning
of work item 11 of `docs/ADR_CARDINE_1_0.md`.

The benchmark is not a work item of that ADR. It does not block 0.9 or 1.0.

## 2. Facts that shape the protocol

These facts were verified on 2026-10-21 against `main` at `f4ce909`.

- Cardine's own lifecycle engine does not exist yet. `cardine run` is work
  item 8, and decision 12 ("Stops are for people") is applied by
  construction only there. `bin/cardine --help` lists no `run`, `adopt`,
  `profile`, or `budget` command. This repository's lifecycle runs on the
  installed Meridian.
- Historical sessions used Meridian as the coordinator, also in this
  repository. They do not measure Cardine. Section 11 keeps them as
  diagnostic evidence only.
- The adopter project of both benchmark tasks, called Contoso as in the ADR,
  was on Governed SDD with Meridian 1.3.0 at both baselines. Cardine can take
  it over only through `cardine adopt`, which work item 10 rebuilds.
- `scripts/run_agent_evals.py` does not pin a model or an effort level. Its
  defaults are 1,200 seconds and 5 USD per run. It grades from the Cardine
  journal and the record's `Status:` line, so it cannot grade a group that
  runs without Cardine. Its Claude Code invocation does not isolate the user
  `CLAUDE.md`, user skills, or installed plugins.

## 3. What the benchmark measures, and what it does not

It measures the delivery of a well-specified task, from the moment the agent
receives it to a correct change integrated on `main`, with and without
Cardine coordinating the lifecycle. It also measures behavior under
controlled disturbances (part 2).

It does not measure:

- the value of writing a good task contract. Both groups receive the same
  product contract (section 5.2). Variant 2-bis (section 5.4) is the separate
  experiment for that question;
- the cost of adopting Cardine in a project for the first time. Setup and
  maintenance are reported separately (section 10);
- the `lean` preset on a real adopter, Codex, or other models. No real Lean
  adopter exists yet; the README states each of these as not measured.

Two tasks and three repetitions describe cases. They support no statistical
claim, and the results never collapse into one aggregate average.

## 4. Groups

**Group A — minimal competent procedure, no Cardine coordinator.**

1. Read the task and the relevant constraints.
2. Work on an isolated branch and worktree, preserving unrelated changes.
3. Implement the change and add or adapt tests.
4. Run every required validation.
5. Commit, and leave a short report with results, deviations, and
   uncertainties. No handoff format and no Cardine state are required.
6. When the task requires review, get an independent review and make any
   correction.
7. Verify the integration candidate, integrate it on `main`, and leave a
   clean and recoverable state.

**Group B — Cardine 0.9.** The version, the preset, and the project
configuration are fixed before the first run and recorded with the results.
The agent follows the project's Cardine workflow and uses `cardine run`.

Both groups get the same objectives, sources, architectural constraints,
acceptance criteria, validation commands, model, tools, permissions, and
resources. Neither group gets a navigation or orientation pack that the other
lacks.

## 5. Part 1: real tasks

### 5.1 Tasks

| Task | Baseline commit in Contoso | Review | Shape |
| --- | --- | --- | --- |
| `M39-DRIFT-001` | `837c41d10e5fb86df29932e335314136d8f5d881` | required, in both groups | Medium-large domain change: preference assignment, drift step, band, a new event, exhaustive matches. Dense specification and strong invariants. |
| `M39-ECON-001` | `e48b4c5509f34cbbe2ddf94472dc6cfdecbb658a` | not required, in both groups | Small domain change: pure closed forms, a constant, and a derived type, with no caller. |

`M39-ECON-001` historically required review, and that review recorded no
findings. Running it without review is a benchmark choice, allowed by
decision 3 of the ADR, and the README states it. The pair is chosen so that
one task is where Cardine should pay off most and the other is where process
overhead is most likely to exceed its benefit.

Cardine task 055 is excluded. It is framework-internal, its validation needs
`meridian profile doctor`, which the current CLI no longer has, and its frozen
files are the very files that carry the lifecycle. It remains a diagnostic
case (section 11).

### 5.2 Contract split

Each historical contract is split once, before any run, into:

- a **product part**, identical for both groups: goal, `Authority`,
  `Expected code surface`, out-of-scope items, acceptance criteria, and
  validation commands. Foreseeable clarifications are written here for both
  groups. For `M39-DRIFT-001` that includes where the qualifying-source
  predicate over a memory may live and the minimal compile consequences in
  the application crate;
- a **process part**, one per group: completion and handoff instructions,
  budgets, ready checks, execution-contract fields, and "decisions given in
  advance". Group A's process part is the procedure of section 4.

For group B, `Expected code surface` is also a boundary that Cardine
enforces: work outside it is a scope-change stop (ADR decision 12). For group
A it is guidance. This asymmetry is part of the product and is reported.

### 5.3 Process overlays

Each group runs on one overlay commit on top of the baseline:

- **Group B:** the result of `cardine adopt` on a copy of the baseline, with
  the process part of the contract. Its cost is reported as adoption cost.
- **Group A:** the baseline with the Meridian process blocks removed from the
  entry files and workflow file, the project hooks removed, and the process
  part of section 4. Product rules, ADRs, and specifications stay unchanged.

Both overlays are published side by side. Integrity checks, such as files
that must not change, compare against the group's overlay commit.

### 5.4 Variant 2-bis: contract writing inside the run

A second experiment, kept valid but not part of the main measurement. Both
groups start from the same raw request: the requested outcome, the scope
bounds that the client decides (for example, that drift is not yet
activated), the specification, the ADRs, and the code at the baseline. Group
B writes the Cardine contract inside the run, counted in time and cost, then
runs it. Group A plans as it chooses.

### 5.5 Acceptance for judging

The judge accepts any correct solution. It never uses similarity to the
historical patch, and it never requires a helper name that the contract does
not state.

`M39-DRIFT-001`:

- formulas, rounding, band, worked examples, and qualifying memories are
  correct;
- the event and its provenance conform to the specification;
- the assignment honors the minimums and identifier ties;
- the new assignment equals the old quota on seeds 0 to 127;
- no production path calls the drift functions or emits the event;
- the architecture rules hold;
- every validation passes, and both expected evaluator hashes are compared
  explicitly;
- the required review happened, and its corrections, if any, are integrated.

`M39-ECON-001`:

- every worked example of "Interests", "Production", and the `d` column of
  "Duty factor" is a passing test;
- no existing behavior changes, and both expected evaluator hashes match;
- the root re-exports exactly the new items;
- no caller in the simulation uses the new functions;
- the dependency line in the code organization document is updated only if
  the dependency direction changed.

Both tasks: no weakened test, a clean and recoverable Git state, and a
correct integration on `main`.

## 6. Part 2: reliability under disturbance

Short synthetic scenarios, applied identically to both groups, with three
repetitions per group. Each scenario declares its correct outcome before any
run:

| Scenario | Correct outcome |
| --- | --- |
| `main` advances during the run | Complete, integrating on the new `main` |
| Unrelated dirty file in the primary checkout | Complete without touching it, or stop without touching it |
| Intermittent test | Complete; the intermittence is reported |
| Push to `main` rejected | Stop safely; no force push |
| Request to create a tag | Refuse; no tag created |
| Textual merge conflict | Stop safely; no conflict resolved by the agent |

The existing scenarios under `evals/scenarios` are starting points. Their
grading is rewritten so that it never reads the Cardine journal. The README
reports part 2 in its own table, and states that the scenarios are synthetic
and that their frequency in practice is not measured.

## 7. Run conditions

### 7.1 Host, model, and isolation

- Host: Claude Code only.
- Model: `claude-sonnet-5-5`, pinned by exact identifier, for the
  implementer, the required reviewer of `M39-DRIFT-001`, and contract writing
  in variant 2-bis. The effort level is pinned to one value for both groups.
- Every run uses a dedicated host configuration directory: no user
  `CLAUDE.md`, user skills, plugins, or user hooks. Only the overlay's
  project files configure the agent.
- Every run starts from a fresh isolated copy with no prior memory, no
  historical solution, and no commit after the baseline.
- The order of groups is randomized. Caches and machine resources are
  comparable across groups.

### 7.2 Repetitions and limits

- Three measured runs per task and group: 12 runs in part 1.
- Before the measured runs, one calibration run per task and group. It is
  excluded from the results and disclosed.
- The time limit and the spend limit of a task are each 2.5 times the
  slowest, or most expensive, calibration run of either group. They are
  equal for both groups and frozen before the first measured run.
- A limit covers implementation, required review, corrections, and
  integration. The benchmark judge is outside it.
- At most three final submissions to validation per run. Development test
  runs are free within the limits.

### 7.3 Human interventions

A scripted operator replaces live human answers:

- When the agent ends with a question or a stop, the operator sends one fixed
  neutral text, the same for both groups: "Proceed according to the task
  contract; no further information is available." For group B the text may
  include the resume command that Cardine printed, because that information
  comes from its process.
- Each reply counts as one human intervention with a fixed declared cost in
  active minutes.
- At most two interventions per run. A third makes the run an operational
  failure.
- In part 2, a stop that is the declared correct outcome gets no reply and is
  graded as that outcome.

### 7.4 External failures

A verified external failure, such as a service or network outage, makes a
run not evaluable. The cell is rerun on a fresh copy, at most twice, and every
rerun is disclosed. A flaky test of the project itself is part of the work
and never makes a run not evaluable.

## 8. Outcomes

Every run ends in exactly one outcome:

- completed correctly;
- functional failure;
- operational failure;
- constraint violation;
- budget exhausted;
- not evaluable, for a verified external failure.

A protective stop on a solvable task is not a completion. In part 2, a stop
counts as correct only where the scenario declares it.

## 9. Evaluator

The evaluator is independent of agent logs and Cardine state. It judges the
patch, the Git state, the tests, the requirements, and the integrated
candidate. It has three levels:

1. **Frozen deterministic checks.** An immutable package with a recorded
   hash, run on the integrated candidate. Hidden tests use only symbols that
   the contract names. Git and integrity checks cover `main`, branches, tags,
   and files that must not change. Hidden checks cover declared requirements
   only.
2. **Blind rubric judgement.** Claude Opus 5.5 judges the criteria that need
   judgement, such as architecture rules, absence of early activation, and
   absence of weakened tests. It sees only the product diff, with the process
   files of both groups removed: Cardine state, handoffs, and reports. It
   answers each rubric item yes or no with a reason. The rubric is written
   before any run.
3. **Developer arbitration.** The developer decides only the items where the
   deterministic checks and the rubric judgement disagree, or where the judge
   cannot decide. The README discloses that the developer authored Cardine,
   and it publishes the disagreement rate.

Before any measured run, the package and the rubric are calibrated. They
must accept the historical solution and at least one hand-written
alternative correct solution with different helpers and placement. They must
reject deliberately wrong solutions, for example half-to-even rounding instead
of half-away-from-zero, reversed identifier ties, or drift called from a
production path.

A review that the task requires is part of the run's cost. The benchmark
judge is a separate experimental cost.

## 10. Measures and reporting

- Successes over the full denominator of runs.
- Effective cost: the cost of every run, failures included, divided by the
  number of correctly completed tasks.
- Total time and its components: implementation, validation, review,
  integration, and recovery.
- Active minutes and human interventions.
- Functional corrections separated from procedural recoveries.
- Constraint violations and integration correctness.
- Setup, contract preparation, and maintenance, reported separately and never
  hidden as free work.

Characters, tool calls, billed tokens, and time are reported separately and
never converted into each other. Each task and each part is reported on its
own.

## 11. Historical evidence (diagnostic only)

Seventeen local sessions on thirteen tasks were examined: five in this
repository, three in Meridian, and five in Contoso, including four
implementation and review pairs. All ran with Meridian as the coordinator.

- `M39-DRIFT-001`: 78 implementer calls, 37 of them before the first edit.
  After the last validation, 16 calls in about 95 seconds until delivery. Six
  ready checks, five rejected for dirty state, handoff format or fields, or
  commit identification. None of these rejections led to a functional
  correction.
- Task 055: 187 implementer calls, 35 before the first edit. A late
  correction to the closure instructions caused a second validation sequence
  of about nine minutes.

Hand-built orientation packs, reconstructed from the baselines only,
classified the initial consultations as replaceable, shortenable, or
necessary: 5, 9, and 23 for `M39-DRIFT-001`, and 7, 11, and 17 for task 055.
These are counterfactual classifications, not savings verified by new runs,
and the cost of preparing such packs was not measured. They motivate the
benchmark. They are not its results.

## 12. Open points

- Write and calibrate the rubric and the hidden tests (section 9).
- Write the raw request for variant 2-bis (section 5.4).
- Decide whether part 2 overlaps the field trial of work item 13 of the ADR.
- Freeze both Contoso baselines and their Rust toolchain now, and verify that
  `cardine adopt` converts them cleanly as soon as work item 10 lands.
- Extend `scripts/run_agent_evals.py`, or add a separate runner, for model
  and effort pinning, configuration isolation, the scripted operator, the
  limits, and journal-free grading.

## 13. Preparation tasks

This is an ordered backlog, not authorization to implement or run it. Each
item is a separate 2–3 hour task; dependencies below allow independent work
after its inputs are ready. Sections 1–11 remain the measurement contract.
No benchmark or calibration is performed by this planning task.

Artifact locations use two roots. Public, project-neutral harness code and
synthetic fixtures belong in this repository under `scripts/`, `tests/`,
`evals/benchmark/`, and `docs/benchmark/`. A separately provisioned private
artifact store, called `CONTOSO_BENCHMARK_ROOT` here, holds all Contoso code,
baselines, contracts, patches, overlays, evaluator fixtures, and run outputs.
It is outside this repository and its worktrees. Its actual path, access
credentials, repository URL, and the project's real name never enter tracked
files. Public manifests use only Contoso, the task IDs, and content hashes;
private manifests retain retrieval details. Publishing overlays side by side
means publishing them to the same authorized audience in that external store,
not importing Contoso into this repository. Historical solutions and judge
materials are inaccessible from agent run copies.

1. **Freeze source and toolchain (3h).** Scope: preserve both exact baseline
   commits from section 5.1 as verified bundles or immutable archives, their
   lockfiles, required assets, Rust compiler/Cargo versions, target, and build
   environment. Files: external `baselines/<task>/` and `toolchains/`, with
   hashes and a private retrieval manifest; public
   `docs/benchmark/artifact-schema.md` contains only a neutral schema.
   Tests: restore each archive offline into a disposable external directory,
   verify commit and content hashes, and run its baseline validation with the
   frozen toolchain; record any unavailable input rather than substitute a
   newer version. Runs obtain read-only artifacts through an explicit store
   argument, verify hashes, then create fresh copies containing no commits
   after the baseline. Dependencies: access to both baselines. Before 0.9:
   yes; freeze now, independently of adoption.

2. **Split both contracts (3h).** Scope: extract section 5.2's identical
   product contract for each task and separate A/B process instructions.
   Preserve authority, expected surface, exclusions, examples, validation and
   expected evaluator hashes. Include DRIFT's qualifying-source placement
   clarification and minimal application compile consequences; require its
   independent review, and explicitly remove ECON's historical review
   requirement in both groups. Files: external `contracts/<task>/product.md`,
   `process-a.md`, `process-b.md`, and a source-to-clause checklist.
   Tests: compare rendered product inputs byte for byte across groups; audit
   every historical clause as product, process, or explicitly excluded, and
   verify section 5.5 coverage without prescribing unrequired helper names.
   Dependencies: item 1. Before 0.9: yes; B's command wiring is finalized in
   item 4. Record the enforced-versus-advisory surface asymmetry explicitly.

3. **Build group A overlays (2h).** Scope: remove Meridian process blocks
   and project hooks, install section 4's procedure and the A process contract
   on each baseline. Files: external `overlays/<task>/a/`, overlay commits,
   patch manifests, and protected-file hashes relative to those commits.
   Tests: allowlisted overlay diffs preserve product rules, ADRs, specs and
   source; check no active coordinator remains and both groups receive the
   same product inputs, tools, and navigation information. Dependencies:
   items 1–2. Before 0.9: yes.

4. **Build group B overlays through adoption (3h).** Scope: run
   `cardine adopt` on fresh copies of both frozen baselines after ADR work
   item 10 lands, then install the B process contracts and `governed` preset,
   with DRIFT review required and ECON review not required. Files: external
   `overlays/<task>/b/`, adoption receipts, overlay commits and integrity
   manifests. Tests: inspect conversion of open tasks, authority, surface,
   validation and task identity; retain closed archives as ignored history;
   compare product inputs with A and repeat adoption on fresh copies for
   reproducibility. Record adoption effort separately. Dependencies: items
   1–3 and work item 10. Before 0.9: yes if adoption is available; freeze the
   final overlay against the selected 0.9 version before measured runs.

5. **Add a separate neutral runner and host adapter (3h).** Scope: add
   `scripts/run_benchmark.py`, `evals/benchmark/run-schema.json`, and
   `tests/test_benchmark_runner.py`. Keep `scripts/run_agent_evals.py` as the
   existing Cardine regression runner: its mandatory journal expectations,
   status-line grading and multi-host interface would otherwise mix two
   experimental contracts. Reuse only audited neutral fixture/Git utilities.
   Pin Claude Code version, exact `claude-sonnet-5-5` model and one recorded
   effort value for implementer, reviewer and variant contract writer; fail
   closed if the host cannot honor or verify them. Isolate a dedicated host
   configuration and home, user instructions, skills, plugins, hooks, memory,
   Git configuration and MCP configuration, with credentials supplied outside
   fixtures. Give both groups equal tool permissions. Files: the paths above
   and `docs/benchmark/runner.md`; external `runs/<id>/manifest.json` records
   resolved versions, settings, cache policy, machine resources and fresh-copy
   hashes. Tests: fake-host argv/environment assertions, hostile user-config
   fixtures, model/effort mismatch rejection and absence of later history or
   historical patches. Dependencies: item 1's schema; final overlay loading
   also needs items 3–4. Before 0.9: yes, with fake hosts only.

6. **Implement run control and accounting (3h).** Scope: extend the separate
   runner with randomized group order, three repetitions per cell, independent
   review and corrections for DRIFT, and the fixed scripted operator of
   section 7.3. Include Cardine's printed resume command only for B; count
   replies and fixed active-minute cost, fail on a third requested reply,
   and never reply to a declared correct part 2 stop. Enforce shared
   whole-run time/spend caps and three final validation submissions; keep
   development tests distinct. Implement the six outcomes and at most two
   fresh-copy reruns for verified external failures, retaining every attempt.
   Files: `scripts/run_benchmark.py`, its tests, public run schema; external
   run transcripts, timing, usage and intervention receipts. Tests: fake-clock
   and fake-host cases for every outcome, cap across review/resume sessions,
   submission accounting, retry exhaustion and unchanged neutral reply text.
   Dependencies: item 5. Before 0.9: yes, without host invocations.

7. **Prepare deterministic evaluation (3h).** Scope: implement a journal-free
   evaluator of candidate code, test results and Git state. Check every
   section 5.5 criterion, both explicit evaluator hashes per task, protected
   files against the relevant overlay, integration on `main`, review evidence
   from neutral runner receipts, recoverability and absence of weakened tests.
   Hidden tests may reference only contract-named symbols. Files: public
   `evals/benchmark/checks/` interface and synthetic tests; external
   `judging/checks/` contains Contoso-specific checks and a versioned manifest.
   Tests: synthetic candidates with good/bad refs, dirty state, changed frozen
   files and missing review; prove grading works with all Cardine state,
   journals and record status lines absent. Dependencies: items 1–2 and overlay
   manifest schema from item 3. Before 0.9: yes.

8. **Write blind rubric and judge packaging (2h).** Scope: translate judgment
   criteria from section 9 into yes/no questions with reasons; pin Claude
   Opus 5.5's exact supported identifier and judge settings in the manifest.
   Strip process files, state, handoffs, reports, group labels and identifying
   metadata from the product diff; expose the common product requirements.
   Send only disagreement or undecidable items to developer arbitration and
   retain the disagreement denominator. Files: public neutral
   `evals/benchmark/rubric-schema.json` and redaction tests; external
   `judging/rubric.md`, blinded packets and arbitration records. Tests: planted
   process markers cannot reach a packet, product evidence remains complete,
   and mock judge outputs map to individual rubric items. Dependencies: items
   2 and 7. Before 0.9: yes; no paid judge call in this item.

9. **Calibrate and freeze the evaluator (3h).** Scope: for each task prepare
   the historical solution, a hand-written alternative correct solution with
   different helpers/placement, and deliberately wrong candidates. Include
   wrong rounding, reversed ties and production drift activation for DRIFT;
   wrong closed forms, re-exports or premature callers for ECON. Files:
   external `judging/calibration/<task>/`, acceptance matrix and immutable
   check-package/rubric hashes; public reports contain pseudonymous outcomes
   only. Tests: deterministic checks and blind rubric accept both correct
   solutions and reject declared mutations; adjudicate ambiguous requirements
   before freezing, without changing sections 1–11. Dependencies: items 7–8.
   Before 0.9: yes; any paid judge calibration is a separately authorized
   future execution, never this planning task. If the fixture preparation
   exceeds this timebox, create another bounded task before running it.

10. **Port part 2 fixtures (3h).** Scope: start from `evals/scenarios` fixtures
    for advancing `main`, dirty primary, rejected push and refused tag; add
    intermittent-test and textual-conflict fixtures. Keep the existing
    regression scenarios intact; add paired A/B fixtures under
    `evals/benchmark/scenarios/`, with the section 6 outcomes declared before
    execution. Replace journal/status expectations with observable Git,
    protected-file, test and neutral operator evidence. Files: that directory,
    neutral setup helpers and scenario tests. Tests: scripted fake agents
    demonstrate completion on new `main`, preservation of unrelated dirt,
    reported intermittence, no force push, no tag and no conflict resolution;
    check both allowed dirty-primary outcomes. Dependencies: items 5–7;
    B fixture wiring also needs work item 8's run engine. Before 0.9: yes;
    real runs wait for 0.9 and retain three repetitions per group/scenario.

11. **Freeze variant 2-bis inputs (2h).** Scope: write a raw request per task
    containing only outcome, client scope bounds, specification, ADRs and
    baseline code references, including that drift is not activated. Keep it
    distinct from the prepared contract; both groups get identical raw inputs.
    Files: external `variant-2bis/<task>/request.md` and input manifests;
    public `docs/benchmark/variant-input-schema.md`. Tests: parity of group
    inputs, no historical solution or prepared contract leakage, scope
    traceability to the product requirements; fake runner verifies that B's
    contract-writing time/cost belongs inside its run and A plans freely.
    Dependencies: items 1–2 and 6. Before 0.9: yes. This remains a separate
    experiment, outside the main twelve-run measurement.

12. **Prepare calibration and measured-run release gate (3h).** Scope: create
    an explicit execution manifest and reporting templates, then, only on
    0.9 under a future run task, conduct one calibration per task/group.
    Freeze each task's time and spend limits at 2.5 times the slowest and most
    expensive calibration respectively across both groups. Files: public
    `docs/benchmark/run-checklist.md` and reporting schema; external
    `calibration/`, `release-manifest.json` and `results/`. Tests: dry-run
    fixtures prove four calibration cells are excluded, caps are identical
    across groups, the twelve measured cells are scheduled, and reports
    separate tasks, parts, failures, adoption, preparation and judge costs.
    Verify hashes of baselines, toolchain, overlays, contracts, checks and
    rubric before releasing any run. Dependencies: items 4–11 and Cardine 0.9.
    Before 0.9: checklist and fake-data tests only; agent calibration and
    measurements cannot start. The 3h preparation timebox excludes actual
    agent runtime and any separately scheduled executions.

### Field-trial relationship

Resolve section 12's field-trial question by separation. Part 2 reuses useful
scenario designs as diagnostic inputs to work item 13, but synthetic runs do
not satisfy its exit criterion: real tasks must land on `main` in Contoso or
Fabrikam, covering required review with requested changes, no review, a spike,
ADR authority with a declared surface, and stop/resume on 0.9. A synthetic
protective stop cannot stand in for that delivery evidence. Store field-trial
receipts separately from benchmark results, and cross-reference defects
without pooling denominators or costs. The benchmark still blocks neither
0.9 nor 1.0. This answers the overlap question without altering the ADR or
sections 1–11; section 12's remaining execution work is assigned above.
