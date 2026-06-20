# Benchmarks, verifier backends, and a terminal UI

**Date:** 2026-06-20

This follow-up consolidates the earlier visualization/backend analysis
(research/19), benchmark strategy (research/20), and the now-completed P4
workbench measurements (research/26). The new question is whether analint should
invest next in more benchmarking infrastructure, multiple verifier backends, or
a terminal UI.

## Decision

1. **Add longitudinal performance tracking.** The existing harness answers
   scaling questions at one revision, but it does not show which commit changed
   validation time or memory. That history is now an explicit project need.
2. **Do not implement a second verifier backend now.** Multiple backends are
   strategically plausible, but current models have not exceeded the reference
   engine's useful range or required a property the source DSL can express but
   the engine cannot check.
3. **Treat a TUI as an optional human client, not core verification work.** It
   may become useful for navigation and trace inspection after the public API and
   documentation cleanup. It is not useful enough to block the first release.
4. **If a TUI is built, start in this repository as an optional extra.** A
   separate repository is justified only after the versioned query and
   exploration contracts are sufficient for an independently released client.

---

## 1. Two meanings of "benchmark"

Earlier research used the word for both:

1. **Evidence/capability models** — realistic projects such as OAuth or
   Kubernetes that exercise the DSL, diagnostics, and verifier semantics.
2. **Performance benchmarks** — stable workloads that measure how runtime and
   memory change as analint evolves.

Both are useful, but they answer different questions. The rest of this section
is about the second meaning.

## 2. What performance work already exists

The repository now has four distinct forms of evidence:

- transition conformance tests for semantic correctness;
- characterization snapshots for graph/result drift;
- generated scaling families with closed-form state counts;
- external models for product and expressiveness evidence.

`scripts/bench_scaling.py` generates counter grids, conserved transfers, and
workflow products from roughly \(10^2\) through \(10^5\) states. It records
states, edges, actions, completeness, time, memory, time/state, bytes/state, and
artifact cost. Small and medium counts are checked by tests; timings are
informational.

A fresh run on 2026-06-20 (CPython 3.14.5, Apple arm64) reproduced the existing
baseline:

| family | states | edges | minimum exploration time | peak memory |
|---|---:|---:|---:|---:|
| counter grid | 10,000 | 36,000 | 0.78 s | 53 MB |
| conserved transfer | 10,626 | 177,100 | 5.26 s | 272 MB |
| workflow product | 16,384 | 86,016 | 4.18 s | 200 MB |

The important result is not a universal speed number. On the same state scale,
the denser transfer graph is much slower and larger. **Edges, enabled-action
checks, and concrete parameter bindings are better cost predictors than states
alone.**

### Current test-suite evidence

The user's perceived slowdown is real:

| workload | current local time |
|---|---:|
| full pytest suite, no coverage | 18.68 s |
| full pytest suite, coverage enabled | 19.62 s |
| `test_characterization.py` alone | 13.02 s |
| Kubernetes characterization case | 6.42 s |
| OAuth characterization case | 5.25 s |

This does not mean normal validation takes six seconds. `scripts/bench.py`
measured the best of five complete `validate()` calls at 0.88 s for Kubernetes
and 0.60 s for OAuth. The characterization test first calls `validate()`, then
builds the spec again and runs every query through a fresh per-query exploration
cache. Kubernetes has six queries and OAuth has eight, so the test repeats much
of the expensive graph work.

That is both:

- a test-harness optimization opportunity: share exploration results while
  preserving the same fingerprint; and
- evidence that performance must be measured at named boundaries rather than
  inferred from total pytest duration.

The current example benchmark also accepts every directory under `examples/`,
so it reported `__pycache__` as a failing zero-time example. Benchmark workload
selection needs the same explicit `spec.py` filter as characterization.

### Required benchmark layers

The minimum useful suite has three layers:

1. **User-path macro benchmarks**
   - cold model preparation/loading;
   - complete `validate()` for one small, one medium, and the two current large
     examples;
   - compact versus full exploration-artifact production.
2. **Engine scaling benchmarks**
   - counter grid, conserved transfer, and workflow product;
   - fixed roughly \(10^3\) and \(10^4\)-state tiers for routine history;
   - \(10^5\) only for manual/nightly stress runs.
3. **Development-loop observations**
   - total pytest duration and the slowest tests;
   - tracked separately because test implementation cost is not framework
     runtime.

Record:

- median wall time and variability;
- peak memory;
- states, edges, roots, concrete actions, and completeness;
- time/state and time/edge;
- Python version, platform, commit, and benchmark schema version.

States and edges are correctness/context metrics, not performance thresholds.
Wall time must not become a normal unit-test gate.

### Longitudinal history

ASV is now justified because its primary purpose exactly matches the requirement:
benchmark one project over its lifetime, store results by commit and machine,
compare revisions, detect regressions, profile a selected benchmark, and publish
static history.

Use it narrowly:

- one controlled Python version and runner for comparable history;
- benchmarks live in this repository;
- a short suite on manual/scheduled CI and before/after engine changes;
- `asv continuous BASE HEAD` for deliberate performance-sensitive PRs;
- no required check until enough runs establish normal variance;
- later warn on a large repeatable regression; do not fail on a single noisy
  percentage.

Keep `scripts/bench_scaling.py` for quick local diagnostics and JSON semantic
metrics. ASV owns revision history and statistical timing; it should call the
same workload builders instead of creating a second set of models.

### What to measure next

Do not invent more workload families up front. Extend the existing families
only when a concrete engine change needs evidence:

- action indexing: vary disabled/enabled action density;
- compact state layout: vary fields and scoped instances per state;
- symmetry reduction: vary interchangeable instances;
- partial-order reduction: vary independent workflow components;
- a future backend: run the same generated semantic cases through both engines.

Keep correctness gates separate from timing. A noisy CI runner may verify state
and edge counts, but must not fail a build because a wall-clock threshold moved.

`hyperfine` is useful only for end-to-end command comparisons such as CLI startup
or installed-wheel overhead. It supports warmups, repeated runs, outlier
detection, parameterization, and JSON export, but it cannot replace the current
in-process harness's semantic metrics or ASV history.

Do not create a public "analint vs Quint/FizzBee" speed leaderboard. Different
state encodings, bounds, property semantics, and completeness guarantees make a
single runtime number easy to misrepresent. Cross-tool work should remain a
modeling and semantic comparison unless an identical bounded transition system
and verdict contract can be demonstrated.

---

## 3. Are multiple backends strategically promising?

Yes, conditionally. They are a plausible escape hatch if analint's value remains
the domain-shaped authoring and maintenance layer while verification needs grow.
They are not yet evidence-backed implementation work.

Three backend classes are materially different:

1. **Reference explicit-state backend** — the current Python BFS. It defines the
   executable semantics and produces exhaustive finite-state results.
2. **Optimized explicit-state backend** — the same graph and verdicts over a
   compact execution plan: integer slots, compiled expressions, indexed actions,
   and compact state storage.
3. **Symbolic/external backend** — bounded SMT or translation to an existing
   verifier. It explores a different representation and requires stronger
   semantic mapping.

Quint demonstrates why multiple backends can be useful: TLC explicitly
enumerates states, while Apalache lowers bounded executions to SMT constraints.
The latter can handle some large numeric domains that enumeration cannot, but
its result is bounded by execution length. A backend choice therefore changes
performance characteristics and sometimes the completeness contract; it is not
just a faster implementation switch.

### Triggers for backend work

Start backend design only when at least one trigger is observed repeatedly:

- real models hit memory/time limits below the useful declared bounds;
- profiling shows object/state representation dominates after cheap algorithmic
  fixes;
- users need a property already present in the analint model but unsupported by
  the current engine;
- an external verifier consumer accepts a precisely documented semantic subset;
- a second frontend or remote service creates a real model-wire-format consumer.

Until then, a backend abstraction is speculative. The current transition kernel
and exploration artifact are sufficient boundaries for the shipped engine.

### Expected implementation cost

Order-of-magnitude estimates for one engineer already familiar with the engine;
they are scope indicators, not delivery promises:

| option | minimum credible scope | rough effort |
|---|---|---:|
| optimized in-process plan | lower current AST/state into slots/opcodes; preserve graph/verdict parity | 2–4 week prototype; 1–2 months hardened |
| external Quint/TLA-style exporter | subset definition, lowering, tool invocation, source/trace mapping, parity tests | 1–2 months for a narrow subset |
| symbolic backend | expression lowering, bounded-path semantics, solver models, diagnostics, unsupported-node policy | 2–4+ months |

The difficult work is not process invocation. It is proving that initial
relations, presence, quantifiers, simultaneous effects, lifecycle rules,
bindings, findings, witnesses, and `PASS/FAIL/INCONCLUSIVE/NOT_CHECKED` retain
their meaning. Every backend needs cross-backend conformance over generated and
external models.

The shortest credible route, if scaling evidence demands one, is an **internal
compact execution plan with the existing Python engine as oracle**. It improves
the common bounded workflow without committing to a public model IR or a second
runtime.

---

## 4. Who would a terminal UI serve?

A TUI primarily serves a human who is learning, reviewing, or debugging a
model:

- browse entities, fields, actions, scenarios, flows, queries, and contracts;
- follow `reads`, `writes`, `affects`, lifecycle, and scenario relationships;
- run checks and filter findings;
- inspect witness/counterexample traces as state diffs;
- optionally step through enabled actions from a valid root.

It adds little for:

- coding agents, which need compact versioned JSON/MCP responses;
- CI, which needs deterministic non-interactive commands and exit codes;
- sharing reviews, where generated HTML/Markdown links are more portable;
- large state graphs, which remain unreadable in a terminal.

The TUI therefore does not strengthen verification. Its product hypothesis is
**lower navigation cost for occasional human users**.

### Smallest useful TUI

A credible first version is read-only:

```text
left:   model tree and fuzzy search
center: selected item / finding / trace
right:  relationships and affected items
bottom: check status and key bindings
```

It should reuse `spec_overview`, `describe`, `affects`, validation results, and
`analint.exploration/v1`. It should not add another model loader, evaluator, or
state representation.

Explicitly exclude from the first version:

- editing Python specifications;
- a generic CLI option form;
- full state-graph rendering;
- a benchmark dashboard;
- arbitrary-state mutation;
- plugin architecture or a public UI SDK.

Trogon can automatically expose a Typer/Click CLI as a form, which improves
option discoverability, but that is not the main analint problem. Model
navigation and trace inspection require a domain-specific UI.

If implemented, Textual is the pragmatic Python choice: it supplies trees,
tables, tabs, command palettes, async workers, headless interaction tests, and
snapshot testing. It also runs over SSH. Keep it behind an optional `tui`
dependency so the verifier/CLI installation remains small.

### Same repository or separate application?

Start in the same repository:

- the client currently needs Python-level query and validation services;
- the public machine contracts are still being stabilized;
- one release keeps compatibility failures visible;
- one small command is cheaper than cross-repository version negotiation.

Split it later only if all are true:

- it consumes only versioned public JSON/MCP contracts;
- it has independent users or maintainers;
- it needs a separate release cadence;
- supporting multiple analint versions is worth the compatibility matrix.

Starting separately now would turn an unproven UI into an integration project.

### Effort and evidence gate

A navigation-only Textual spike is roughly 2–4 days. A usable read-only
navigator with loading/error states, filtering, trace screens, packaging, and
tests is roughly 1–2 weeks. Interactive stepping, branching, rewind, and
disabled-guard explanations would add roughly 2–4 weeks. The cost grows around
background validation, cancellation, large-result virtualization,
keyboard/mouse behavior, terminal-size handling, and visual regression tests.

Do not schedule it before the current API cleanup and first-release
documentation. Reconsider after human usage reveals one of these repeated
problems:

- users cannot discover `show`/`affects` relationships from the CLI/docs;
- trace review requires repeated commands and manual context reconstruction;
- interactive stepping materially finds model mistakes faster than existing
  traces and scenarios.

If evidence appears, build the read-only navigator first. Interactive stepping
is a second milestone, not part of the initial TUI.

---

## 5. Roadmap consequence

The order remains:

1. finish the bounded public-API cleanup and documentation;
2. add a small ASV history suite over existing real and generated workloads;
3. fix avoidable benchmark/test-harness duplication before engine optimization;
4. improve the reference engine only from profiles of real/generated models;
5. prototype a read-only TUI only after repeated human-navigation pain;
6. design another backend only after a scaling/property/consumer trigger.

This keeps the architecture open to both ideas without paying for either before
there is a user problem.

## Sources

- Textual overview, widgets, SSH/CLI use:
  https://textual.textualize.io/
- Textual headless interaction and snapshot testing:
  https://textual.textualize.io/guide/testing/
- Trogon CLI-to-TUI generation and Typer integration:
  https://github.com/Textualize/trogon
- Hyperfine benchmark features and JSON export:
  https://github.com/sharkdp/hyperfine
- Airspeed Velocity performance-history tooling:
  https://asv.readthedocs.io/en/stable/
- Quint TLC and Apalache backend distinction:
  https://quint.sh/docs/model-checkers
- FizzBee interactive Explorer and sequence visualization:
  https://fizzbee.io/design/tutorials/visualizations/
