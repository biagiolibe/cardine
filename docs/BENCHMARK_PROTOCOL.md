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
