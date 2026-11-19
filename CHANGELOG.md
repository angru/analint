# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is
`0.x` the public API may change between minor releases.

## [Unreleased]

## [0.2.0] — 2026-11-19

Author finite models with enum lookup, floor division and one-sided saturation;
use the correctness and diagnostic repairs below. Review the
[migration notes](docs/dsl.md#migrating-to-020) for inherited query budgets,
stricter saturation and multi-root reachability.

### Added

- `Lookup(selector, mapping)` provides an exhaustive enum-to-integer expression
  with copied tables, parameter/quantifier binding, slicing and cache support.
  Unmatched selectors fail; scalar enums retain Python equality. TLC exports
  proven enum domains and explicitly refuses unsupported selectors. (#49, #59)

- Integer `//` expressions, including reflected forms and parameter/quantifier
  binding, floor toward negative infinity. Zero divisors and non-numeric
  operands fail explicitly; native numeric equality follows Python. TLC supports nonzero constant integer divisors
  and refuses dynamic divisors without approximating them. (#49, #58)

- `Flow(name=...)` supplies a display label in terminal/JSON reports and `show flow`.
  Stable ids, selection and existing positional arguments are unchanged. (#47)

- `Field(saturate="low" / "high")` clamps only the selected inclusive bound.
  The opposite bound and other constraints remain hard, including for `Create`.
  Native transitions and TLC apply constraints after clamping; initial values
  and event payloads are never clamped. (#50)

### Changed

- `saturate=True` now checks `values` and exclusive `gt`/`lt` constraints after
  clamping, just like one-sided saturation. Existing models that relied on those
  constraints being skipped can now report transition defects. (#50)

- Queries with an omitted or `None` budget inherit `Spec.max_states`, including
  queries with their own roots. Explicit query budgets and invocation overrides
  retain priority. `show`, `check`, `explore` and `trace` use the same effective
  budget without mutating declarations. Set `max_states=10_000` on a query to
  preserve the old independent default. (#48)

### Fixed

- Numeric `Param` operands support multiplication and ordered comparisons directly,
  including literal/parameter and reflected forms. Parameter fields also support
  multiplication; binding uses the existing expression semantics. (#46)

- `Reachable` explains when an initial state is invalid under model invariants
  and was not expanded, instead of presenting it as an ordinary missing path.
  Root legality remains a blocking failure; mixed-root failures still identify
  a legal root without a path. Native/TLC traces and cached checks retain the
  explanation. (#54)

- Terminal reports count structural errors and preserve literal finding locations
  and messages. Load failures show the source file/line when available and stop
  before sections for checks that never ran. Exit codes are unchanged. (#43–#45)

- `DeadActions` preserves disable-only flag writers when the assessed action's
  guard needs the off state. Previously slicing could omit its enabling path
  and falsely report the action dead, depending on action order and budget.
  Ordinary antitone action/property slices retain the optimization. (#41)

- Multi-root `Reachable` now requires a path from every admissible initial
  state, matching the documented contract. Previously one root's witness could
  produce a false PASS. Converging paths are checked on the graph, not assigned
  to their BFS discovery root. Failures identify a root without a path; partial
  exploration stays INCONCLUSIVE unless all roots have witnesses. TLC checks
  roots separately and retains one representative action trace. Existing models
  relying on existential choice among roots can now fail. (#42)

- Repeated checks and traces now observe nested invariant edits and copies of
  previously checked models. Compiled predicates and presence-dependent
  applicability plans belong to one exploration or verification scan, rather
  than the editable invariant. This prevents false PASS results after changing
  a bound, a nested list, or the referenced instance. (#11)

## [0.1.0] — 2026-11-18

Select checks over a shared model, inspect scoped diagnostics, and use the
verification-boundary fixes below. See the [migration notes](docs/dsl.md#migrating-to-010)
for incompatible literal and truthiness changes and the
[selection contract](docs/cli.md#selecting-checks-over-one-model) for verdict scope.

### Added

- Reproducible fulfillment requirement-change trial over one shared model:
  44 full/selected and sliced/whole cases, including an off-flow cancellation
  without refund. CI compares verdicts, per-query state counts, flow outcomes and
  action counts with the committed record; timing and size observations are not
  gates. The source archive includes the record and runs this check against the
  built wheel. (#37)

- Selected `AlwaysHolds` and `Unreachable` queries can discharge supporting
  invariant proofs after a complete, applicable unconstrained PASS, natively or
  through TLC. Counterexamples and unsuccessful attempts return to constrained
  verification. Root legality, relevant transition defects, explicit invariant
  requests and all-action diagnostics remain enforced; own-root attempts never
  borrow canonical trust. (#28)

- Executable AST coverage inventory and bounded fixed-seed conformance probes
  for slicing, compiled evaluation and disk cache parity, including constrained
  emitted payloads. The source-archive release gate runs both suites. (#14)

- TLC exports supported emitted payload constraints, including optional values,
  instead of refusing every constrained template. It checks the post-state and
  reports invalid payloads without clamping. (#24)
- Select flows, queries and invariant checks through repeatable CLI `--check`,
  MCP `checks`, or Python `validate(..., checks=...)`. `validate_spec` reuses an
  existing Spec without reconstructing or filtering the system's behavior.
  Reports distinguish selected, supporting and unselected checks; canonical
  invariant proofs are selected by dependency; action-defect coverage is retained.
  Unknown/ambiguous selections and empty scenario matches are usage errors.
- Trace accepts matching budget, slicing, cache and TLC settings through the
  shared verification pipeline. TLC traces expose their parsed action sequence
  with unavailable state snapshots explicitly marked, without a native rerun.

- Explicit selections now report unrelated invariant/action defects in
  `model_findings` with bounded `model_coverage`, outside verdict and strict-mode
  aggregation. Requested checks, supporting proofs, relevant defects, structural
  validation and root legality still gate the selected result. Unfiltered checks
  retain their original behavior. This can change a selected check from FAIL/exit 1
  to PASS/exit 0 even while unrelated ERROR diagnostics remain visible.
- Trace exposes the same scoped diagnostics. TLC preserves the transition system
  while selecting defect assertions belonging to the requested proof's dependencies.

### Changed

- Clarified the TLC reporting contract: a transition defect remains in both
  its property's findings and aggregate exploration findings so attribution and
  FAIL/exit 1 are preserved. Section/group counts are not unique-defect counts;
  the property may remain INCONCLUSIVE. This documents existing behavior. (#32)

- **Breaking:** native operand literals are now limited to `None`, `bool`, `int`,
  `float`, `str`, `Enum`, and `InstanceRef`. Declared `Entity` classes remain
  supported identities for parameter filters. Other Python objects, including
  `decimal.Decimal` and `datetime.date` literals that previously worked in native
  checks, now produce `structural.invalid_entry` errors. Specs using these types
  must convert their literals and corresponding modeled field values to supported
  representations. This explicit domain also rejects opaque objects wrapping
  field references, preventing false PASS results. (#14)

### Fixed

- TLC transition defects attempted directly from a root now show
  `(initial state) → action` instead of only the attempted action. Non-empty
  paths, property status and aggregate verdict behavior are unchanged. (#32)

- Selected checks no longer repeat an illegal root as an unrelated model
  diagnostic when a blocking root finding already represents it. Internal
  state provenance survives the exploration cache; later violations, other
  roots and findings without matching provenance are preserved. Verdicts and
  public finding schemas are unchanged. (#29)

- `affects` and dependency-bearing `show` requests return structured errors for
  unsupported nodes/effects through Python, CLI and MCP, with guidance to run
  `analint check`; the CLI exits 1 without a private-exception traceback. (#14)

- Reject unknown symbolic operands and predicate subclasses during structural
  validation instead of accepting them as constants or empty trees. Interpreted
  and compiled evaluation reject unknown symbolic operands, slicing falls back
  to the whole model, and impact analysis refuses unknown effects. Cache encoding
  accepts only audited dataclass schemas; TLA export rejects unknown effects
  instead of silently dropping them. (#14)

- Parameter-family bindings refresh guards, effects, postconditions and payloads
  from the current declaration on each bind/expansion, preserving bound-action
  identity for scenarios and flows. Family-owned memos replace the process-global
  registry; copied families cannot reuse another family's bound instances.
  Existing Specs are not automatically re-expanded after template edits. (#11)
- Transition defects discovered only by TLC now make unfiltered runs FAIL
  (exit 1), matching explicit check selections, instead of leaving the aggregate
  INCONCLUSIVE (exit 4). The target property can remain undecided; diagnostics
  include the attempted action. Custom event constructors and literal strings
  colliding with TLC's null sentinel are explicitly refused.
- Symbolic DSL expressions now reject Python boolean conversion (`and`/`or`,
  `if`, chained comparisons) with explicit guidance instead of silently dropping
  conditions. Constrained symbolic event templates still load, with value
  validation deferred until materialization. ([#15](https://github.com/angru/analint/pull/15))
- Persistent MCP tools read current model sources in a fresh worker per request,
  including same-size/same-timestamp edits. Unexpected worker failures retain
  bounded error diagnostics. ([#16](https://github.com/angru/analint/pull/16))
- Explore and trace return load errors when a what-if hypothesis fails to load,
  instead of returning an artifact of the unpatched model. ([#17](https://github.com/angru/analint/pull/17))
- Compiled action plans are scoped to an exploration and rebuilt for later runs,
  so declaration edits cannot reuse stale guards or effects.
  ([#18](https://github.com/angru/analint/pull/18))
- Previously passing `AlwaysHolds`, `Unreachable` and `NoDeadEnd` checks now
  return `INCONCLUSIVE` (CLI exit **4**) when an event-payload subscriber is
  excluded from the explored slice (or the whole model with `--no-slice`).
  CI scripts must handle this exit code rather than treating those checks as
  proved. A `Reachable` search without a witness and `NoDeadEnd` failures also
  remain inconclusive when missing transitions could change the answer.
  Already found reachability witnesses and safety counterexamples remain
  conclusive.
- Invalid materialized event payloads now produce `transition.field_constraint`
  findings and failing scenarios/flows instead of escaping as exceptions.
  Payloads retain non-clamping event-construction semantics; unexpected
  constructor errors are evaluation findings. TLC checks supported payload bounds
  and explicitly refuses unsupported exports. ([#20](https://github.com/angru/analint/issues/20))
- Concurrent TLC runs now isolate Java's extracted standard-module files per
  invocation, preventing shared temporary-file races between agents or MCP
  workers. ([#23](https://github.com/angru/analint/issues/23))

## [0.0.7] — 2026-11-10

### Added

- Compact check JSON via `--format json --compact` or MCP `compact=true`.
  Findings are grouped by code, severity and expected disposition within each
  check result, with full counts and up to three examples per group.
  The Kubernetes admission regression produces 98.69% less JSON in compact
  mode. ([#6](https://github.com/angru/analint/pull/6))

## [0.0.6] — 2026-11-10

Inspect queries and parameterized action families and classify findings by stable
diagnostic code. This release includes the automated artifact checks and Python
3.15 CI coverage.

### Added

- Stable diagnostic codes on every JSON finding (`code`, e.g.
  `structural.no_scenarios`, `transition.pre_failed`) in `check` reports and
  exploration artifacts, documented in the CLI reference. Rejection reasons in a
  passing `Expect.FAIL` scenario carry `"expected": true`. Verdicts are
  unchanged. The `check --cache` format is bumped, so old entries are ignored.
  Existing Python calls to `analint.reporter.Finding` can omit the code.
  ([#5](https://github.com/angru/analint/issues/5))
- Query inspection with `show query ID`: type, predicate/goal, declared budget
  and effective declarative roots, without enumeration or verification.
  Singular `show query` and `show entity` list the same ids as their plurals.
- `show action FAMILY_ID` resolves declared parameterized action families,
  including those with no variants. It shows domains, static `where`, the shared
  contract, existing concrete variant ids and related scenarios/flows. Concrete
  action lookup retains its format and takes precedence. Both inspection
  features share the existing v1 JSON contract through CLI and MCP.
- One release-acceptance entry point, `scripts/check_release.py`, shared by
  Quality CI and the publishing workflow on Python 3.12–3.15. It checks clean
  CLI installs, verdict/exit-code agreement, cache/what-if parity, real MCP stdio
  calls and focused tests executed from the source archive against the wheel.
  Strict metadata/tag checks reject mixed or stale artifacts. Registry jobs
  require verification of the exact uploaded build artifacts; manual Publish
  runs can use `verify_only=true` to exercise the gate without an upload.
- Dedicated TLC conformance CI job with Temurin Java 17 and the official TLA+
  1.7.4 JAR pinned by SHA-256. Missing tools fail the preflight; the existing
  backend, fixed-root, scoped-key and initial-presence tests run against TLC.
- Python 3.15 in the test and clean-install CI matrices and package classifiers.
  The minimum supported Python version remains 3.12.

### Changed

- Refresh the locked Pydantic/core and required typing dependencies so the
  Python 3.15 development install uses a native wheel instead of building core
  from source.

## [0.0.5] — 2026-11-06

Complete impact-analysis output for initialization, expressions and scoped
presence without changing transition semantics or inspection schema versions.

### Fixed

- Impact analysis includes explicit and default field initialization by `Create`,
  preserving writer-to-scenario links and entity writer summaries (issue #4).
  Create field entries identify `explicit` or `default` initialization; deletion
  is reported as a presence change rather than a field assignment.
- `affects` and entity descriptions include reads from effect RHS expressions,
  old Add/Subtract targets, emitted payload expressions and lifecycle guards.
  Nested arithmetic, finite quantifiers and aggregates contribute dependencies;
  expression-based event bindings and payload-only scenarios are no longer omitted.

### Added

- Additive presence metadata in the existing v1 inspection schemas: action
  `presence_reads`/`presence_writes` and entity
  `presence_read_by`/`presence_written_by`. Membership-only invariants now name
  their entity in inspection output. Key literals remain independent of state.

## [0.0.4] — 2026-10-30

Declare fixed initial worlds, use scope keys as domain values, and make empty
initial scopes explicit. Existing scope defaults and transition semantics stay
unchanged. The OAuth and Kubernetes examples use the new APIs; their instance
labels and expanded action IDs change, with equivalent reachable behavior.

### Added

- Fixed initial relations: `Initial(given=[...])` or `Initial(vary=[], ...)`
  builds one candidate from defaults plus the supplied snapshots, with the
  usual `where` filtering and fail-closed errors. `Initial()` uses defaults.
  Non-empty `vary` retains its existing multi-root semantics.
- `Key(ref_or_param_or_bound)` exposes the declared scope key as a
  state-independent value expression, including for absent slots. It supports
  parameter filters, finite quantifiers/aggregates, effects and event payloads,
  compiled predicates, property slicing, persistent cache and exact TLC export
  (or explicit refusal for values TLC cannot encode).
- `Scope(..., initially_present=False)` opts into absent canonical/query defaults.
  Explicit snapshots override the policy; the default remains present and
  scenario/flow partial worlds retain their existing behavior. Read-only scope
  metadata includes `initially_present` as an additive JSON field.

### Changed

- OAuth and Kubernetes use domain Enum values as scope keys and `Key(...)` in
  place of parallel identity parameters. Kubernetes declares its Pod scope
  initially absent. Their complete graphs are unchanged up to the documented
  key/action-id renaming: OAuth 1,169 states / 2,256 edges, Kubernetes 1,792
  states / 13,008 edges. Scoped labels and expanded action IDs change; the
  exploration/trace schema versions and scalar encodings stay the same.

### Fixed

- TLC preserves Python scalar equality for string-based Enum and IntEnum
  values, including `Key(...)` expressions compared with their underlying
  strings or integers. The previous symbolic encoding could incorrectly prove
  an unreachable query after Python exhausted its state budget. Regression
  checks pin the same failing verdict and trace through the fallback. Floating
  Enum subclasses are explicitly refused by TLC, like ordinary float values.

## [0.0.3] — 2026-10-30
Adds persistent exploration caching and incremental exploration without changing
the declared DSL semantics or the versioned JSON contracts.

### Added

- Dedicated documentation pages for the first-spec tutorial, verification
  concepts, DSL and CLI references, MCP tool arguments and examples gallery.
  Documentation CI now validates pull requests with a strict site build and
  executes the tutorial, its planted-defect counterexample and its hypothesis.
  Source distributions include those documentation sources so the shipped
  tutorial tests can also run from an extracted archive.
- `check --cache` (MCP `cache`): explorations are stored on disk
  (`~/.cache/analint`, `$ANALINT_CACHE_DIR`), keyed by a digest of their
  slice, roots, budget and the engine source. A repeated check explores only
  the slices an edit touched, and reports exactly what a fresh run reports.
  On the broker benchmark a warm run takes 0.6–1.0 s instead of 2.7–5.3 s.

### Changed

- Exploration skips work that cannot change the result. An action a guard
  rejected stays rejected in a successor whose transition wrote nothing the
  guard reads, and a successor re-checks only the invariants that read what
  the transition wrote. Graphs and findings are identical; `check` is
  1.2–1.55× faster on the broker benchmark.

### Fixed

- The optional MCP extra is constrained to SDK 1.x, whose `FastMCP` API the
  server uses. A fresh install previously selected incompatible SDK 2.x and
  failed to start; clean-install CI now checks server tool discovery.
- Source distributions include the benchmark models and scripts required by
  their shipped tests. CI now collects the archive's tests against a clean
  wheel installation, catching missing test inputs before release.

## [0.0.2] — 2026-10-11

Scaling release: each check runs on its own slice of the model, states take
far less memory, and checks the budget cannot finish can be handed to TLC.
One breaking change: the model is exactly what `Spec` lists.

### Added

- **Property slicing** (research/34 §5): `check` verifies every invariant and
  query on its cone of influence instead of the whole model. Specs with
  independent processes no longer pay for the product of all of them. The
  result is exact: a conformance test pins it against the whole-model path on
  every example. JSON reports each check's `slice`; `check --no-slice` (MCP
  `slice=false`) restores whole-model exploration.
- Slices skip writers that only switch a flag off (a spent one-time code, a
  closed profile): processes that share such a flag no longer join each
  other's slices. Exact; NoDeadEnd and properties reading the flag keep them.
- `check --tlc` (MCP `tlc`, research/36 R6): invariants and
  Reachable/Unreachable/AlwaysHolds queries that the budget left INCONCLUSIVE
  are exported, on their slice, to TLA+ and decided by TLC (`backend: "tlc"`).
  The export mirrors the kernel exactly and refuses what it cannot mirror; a
  TLC-gated test pins state counts and verdicts against analint.
- An INCONCLUSIVE result names the numeric fields in its slice that actions
  change with no Field bound in that direction (the usual reason a state
  space never closes). If there are none, it suggests raising `max_states`
  or `--tlc`.
- `check --max-states N` (MCP `max_states`) overrides every exploration budget
  for one run.
- `analint trace` accepts a failing invariant: a canonical counterexample with
  state diffs (`analint.trace/v1`, with `invariant` in place of `query`).
  Traces follow the slice `check` decided on; `--no-slice` traces the whole
  model.
- Per-check timing: `elapsed_ms` in JSON, elapsed time in terminal output.
- Warning for a behaviour object defined in a spec module but not part of the
  model.
- `examples/broker`: a generic retail broker (verification, trading accounts,
  payments) as one `Contract` per process — the scaling benchmark.

### Changed

- **Breaking (research/35 step 4):** the model is exactly what `Spec` and its
  imported `Contract`s list. Module globals are no longer scanned for
  membership, and there is no per-field mixed mode; entities, events, scopes
  and inline lifecycles are derived from the behaviour that references them.
  A `Spec` that lists no behaviour is an "empty model" error, and a defined
  but unlisted action, invariant, scenario, flow or query is reported as an
  orphan. Migrate with `Spec(..., actions=[...], scenarios=[...], ...)` or one
  `Contract` per process. `--what-if` still merges its file's objects.

- The summary separates budget-exhausted invariants (`inconclusive`) from
  invariants that could not be checked at all (`not checked`). JSON adds
  `invariants_inconclusive` and `invariants_not_checked`;
  `invariants_unchecked` remains their sum.
- Quantified and aggregate invariants are evaluated over the present members
  of a Scope; an absent member no longer makes them inapplicable. A direct
  read of an absent slot still skips the invariant, as does a member missing
  from a scenario `given`.
- Explored states take 8–15× less memory: a state is a compact key, and its
  context is rebuilt on demand (research/36 R4).
- Exploration is about 5× faster on whole-model runs (shared canonical
  exploration, copy-on-write effects, cached guard plans and state layout).
  Guards and invariants are also compiled into closures, which mirror the
  interpreter (another ~1.8×).

### Fixed

- An invariant never applicable in a *capped* exploration was reported
  NOT_CHECKED ("never evaluable") instead of INCONCLUSIVE.
- A parameterized action without an explicit `id` composed through
  `Contract` + `Spec(imports=...)` kept empty instance ids.
- A long-lived process (MCP, repeated `--what-if` loads) could bind a
  parameterized action from a collected one whose memory address was reused.

## [0.0.1] — 2026-06-21

First public release. The engine and CLI are mature and covered by an extensive
test suite; this release makes them installable and documents their scope.

### Added

- **DSL** for declaring system behaviour in Python: `Entity` with field
  constraints, `Invariant`, `Action` (`pre` / `effect` / `post` / `emits`),
  `Event`, `Lifecycle`, `Scenario`, `Flow`, parameterized actions
  (`Param`), finite quantifiers/aggregates, `Scope` multiplicity, and `Spec` as
  the top-level aggregate.
- **Validator** with a single transition kernel shared by scenarios, flows, and
  the explorer; structural validation; scenario execution; executable multi-step
  flows.
- **Bounded reachability engine**: BFS over a finite state graph with reachability
  queries (`Reachable`, `Unreachable`, `AlwaysHolds`, `NoDeadEnd`, `DeadActions`),
  state-diff witness/counterexample traces, and a deterministic
  `analint.exploration/v1` artifact.
- **CLI** `analint`: `check`, `show`, `affects`, `explore`, `trace`, with
  `--what-if` hypothesis testing, terminal and JSON output, and meaningful exit
  codes.
- **MCP server** (`analint-mcp`, optional `mcp` extra) exposing the same surface
  to AI agents.
- **Examples** spanning business analytics, game/narrative rules, and two external
  evidence models (GitHub branch protection, OAuth 2.0 auth-code + PKCE), plus a
  project-sized Kubernetes ReplicaSet dogfood.

### Scope and honesty

- Verification is **bounded reachability** over a finite state space: it checks
  safety and reachability and reports a three-valued verdict
  (`PASS` / `FAIL` / `INCONCLUSIVE`), preferring `INCONCLUSIVE` / `NOT_CHECKED`
  over a silent pass.
- It deliberately does **not** model liveness or temporal "eventually"
  properties. This is a scope boundary, not a defect.

[0.0.4]: https://github.com/angru/analint/releases/tag/v0.0.4
[0.0.3]: https://github.com/angru/analint/releases/tag/v0.0.3
[0.0.2]: https://github.com/angru/analint/releases/tag/v0.0.2
[0.0.1]: https://github.com/angru/analint/releases/tag/v0.0.1
