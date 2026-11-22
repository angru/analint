# CLI reference

The examples below use the [tutorial model](getting-started.md). Replace `.`
with a directory containing `spec.py` or the path to an entry-point Python file.
Run `analint --help` or `analint COMMAND --help` for installed-version options.

## check

```bash
analint check .
analint .                         # shorthand
analint check . --format json
analint check . --format json --compact
analint check . --strict
```

Checks loading and structure, scenarios, flows, canonical invariants and queries.
The overall verdict includes all of these stages.

| Option | Meaning |
| --- | --- |
| `-f, --format terminal\|json` | Select human-readable or JSON output |
| `--compact` | Group and sample findings in JSON output (requires `--format json`) |
| `--check ID` | 0.1.0: select a flow, query or invariant; repeat or use `KIND:ID` |
| `-s, --scenario ID` | Filter scenarios by id; repeat for multiple ids |
| `-t, --tag TAG` | Filter scenarios by tag; repeat for multiple tags |
| `--strict` | Warnings fail the run |
| `--what-if FILE.py` | Merge hypothesis objects for this invocation |
| `--max-states N` | Override canonical and query budgets with a positive integer |
| `--no-slice` | Use whole-model exploration instead of property slices |
| `--tlc` | Hand supported INCONCLUSIVE properties to TLC |
| `--tlc-timeout SECONDS` | Timeout per exported TLC check, at least 1 second; default unlimited |
| `--cache` | Since 0.0.3: persist/reuse explorations of unchanged slices |

Scenario/tag filters select scenario execution; they do not turn the command
into a scenario-only validation that skips invariants, flows or queries.

### Selecting checks over one model

Available in 0.1.0.

`--check` changes the checks to run, not the system being checked. It retains
all declared actions, constraints and roots. For example, from a source checkout:

```bash
analint check benchmarks/shared_checks.py --check checkout
analint check benchmarks/shared_checks.py --check release_reservation
analint check benchmarks/shared_checks.py --check query:shipment_keeps_reservation
analint check benchmarks/shared_checks.py --check checkout --check can_ship --max-states 100
```

Without `--check`, the existing full-check behavior remains. With it, only the
named flows/properties and their supporting checks run; add `--scenario`/`--tag`
to include matching scenarios.
Scenario ids and tags intersect as before. Unknown ids/tags, ambiguous check ids,
and filters matching no scenarios fail as usage errors (exit 2). Bare check ids
must be unique across flows, queries and invariants; `flow:ID`, `query:ID` and
`invariant:ID` disambiguate. Repeated selectors are deduplicated.

Structural validation always covers the whole model, including unselected
behavior. Flows keep their own `given`; queries keep their declared roots or the
canonical initial relation. No selection changes roots or mutates budgets.

An explicit `--check` run proves **only dependency-related supporting invariants**.
With slicing, selected `AlwaysHolds` and `Unreachable` queries first attempt a
proof without invariant pruning. A complete, applicable PASS with legal roots
and no transition errors discharges that query's supporting invariant proofs.
With `--tlc`, TLC can complete a capped attempt. Counterexamples, evaluation
errors, exclusions, unsupported exports and other unsuccessful attempts use the
ordinary constrained pipeline; a speculative counterexample is never reported
as a real failure without rechecking it. `Reachable` witnesses retain constrained
path validation, and explicitly requested invariants are still proved.

This works with canonical or query-owned roots. An own-root safety proof is
independent and never borrows or grants canonical invariant trust. Other queries
request dependency proofs as before; the set grows when invariant constraints
are needed. An invariant proved without constraints needs no further support.
This is a dependency analysis, not logical minimization of predicates.
Budgets can affect which proof strategy succeeds and therefore which supporting
checks are needed. `--no-slice` uses a conservative constrained
dependency closure and still explores the whole state space.

The verdict and exit code aggregate requested checks, their supporting proofs,
and relevant transition defects. **0.3.0:** sliced selections explore the
selected and supporting slices, with action-slice defect coverage seeded by
their dependencies. A clean unconstrained safety proof supplies its own
coverage. For example, `analint check benchmarks/independent_checks.py --check safe_a`
passes and identifies `bump_b` as unassessed. The unfiltered check still fails
on B's invariant. Flow-only requests check applicable invariants at each step
and skip global exploration.

Findings outside the selected dependencies that are encountered during this
work still go into **`model_findings`**. These findings retain severity, code,
location and trace text and affect neither the selected verdict nor `--strict`.
**`model_coverage`** reports bounded reachability coverage, including root sets,
exploration/state counts, caps and excluded actions. The counts include reused
graphs and successful safety proofs and exclude unsuccessful speculative
attempts. `model_coverage.scope` is `selected_slices_from_verification_roots`
for sliced selections (including whole-model fallbacks) and
`actions_from_verification_roots` with `--no-slice`.

Structural errors, load failures and invalid declared initial relations remain
blocking. Every invariant still participates in initial-state legality: an illegal
root affects the requested verification even when the invariant reads other fields.
**0.1.0:** when exploration reports that same illegal root, its duplicate
non-blocking model diagnostic is suppressed using recorded state provenance.
The blocking root failure remains. Later violations and diagnostics without
matching provenance are retained; sharing a code or invariant location is not
enough to merge them. Full reports may therefore contain several paths to the
same invariant. Use `--compact` to group these findings without treating the
group count as a count of unique defects.
`NoDeadEnd` retains global support because any invariant violation can strand a
full-model state; `DeadActions` asks about all actions. Unknown dependency analysis
falls back to the whole model. No action or invariant is removed from the model.

Filtered JSON reports add `selection` (also in compact mode): `requested`,
`supporting`, `not_selected`, `dependencies`, full `model_actions`, `action_coverage`,
selected-scope `excluded_actions`, effective `options` and `budgets`. Explicit
check selections also list `covered_actions` (included in bounded reachability
coverage at one or more verification root sets) and `unassessed_actions`
(outside that coverage). Transition defects and fireability of unassessed
actions are outside the report's reachability scope. Actions excluded within
the covered slices are listed separately in `model_coverage.excluded_actions`.
Dependencies identify actions and constraints used by each check, including
whole-model fallback. Caps and exclusions can limit coverage within a slice.
A successful unconstrained safety proof can establish absence of defects on
its slice. Its graph may include paths that invariant pruning would block, so
inclusion in `covered_actions` alone establishes no fireability verdict.
Found witnesses and counterexamples remain conclusive.

Each sliced check spends its budget on its own dependencies. For example, a
safety check with a large budget and a witness check with a small budget can
both pass even if extra exploration would find a defect in an action only
the witness depends on. With `--no-slice`, the safety check's larger
whole-model exploration can discover that defect, which then blocks the
combined verdict when the checks share verification roots.

A selected PASS establishes only its reported scope. `--strict` still applies to
warnings in verdict-bearing sections, including structural warnings about the
whole model. Scenario/tag filters without `--check` retain full-check behavior.
Run an unfiltered check for full validation. A selection is only as cheap as
its slices: when a selected property's slice spans most of the model (for
example, 32 of 33 actions because every action touches a shared balance), the
selection explores about as much as a full check and is not faster. An unsuccessful safety attempt
can add work before the constrained retry.
`benchmarks/safety_bridge.py` demonstrates a passing local safety query whose
bridge constraint would otherwise pull in broken, unrelated proofs. The selected
run passes while the unfiltered run fails; no system actions are removed.

The cache directory defaults to `~/.cache/analint`; set `ANALINT_CACHE_DIR` to
override it. Caching does not change findings or completeness. Timings measure
performed work, so a reused exploration is cheaper than a fresh one.

### JSON reports

`check --format json` returns `analint.check/v1`. Read `verdict` and `passed`
before inspecting individual results. `passed` is true only for an effective
PASS, including the effect of `--strict`.

| Field | Contents |
| --- | --- |
| `spec` | Root id and name |
| `load_errors`, `structural` | Load problems and structural findings |
| `scenarios`, `flows` | Example/journey results and findings |
| `invariants`, `queries` | Per-property status, state count, trace and findings |
| `exploration` | Findings encountered while exploring transitions |
| `summary` | Aggregated counts, including inconclusive and unchecked invariants |

Property results can include `slice`, `elapsed_ms` and `backend: "tlc"`.
`elapsed_ms` measures incremental work for that property; shared exploration is
charged to its first consumer, and invariant retries are included. Query timing
includes safety attempts (even discarded attempts) and action coverage requested
by that query. Model preparation and invariant-phase shared action coverage are
excluded. Summing these timings does not give total command time.

**0.3.0:** invariant, `Unreachable`, `Reachable`, `DeadActions` and
`NoDeadEnd` results
can include a `model` object. Its `relation` is `over-approx` for a projected
safety proof, `under-approx: replayed` for concrete evidence confirmed by
replay, `exact` for a deciding exact retry, or `null` for an inconclusive
retry. Safety projections can decide both full and selected checks. An
exclusion can be ignored for a safety proof if the excluded action leaves
every retained field and slot's presence unchanged. Transition coverage
still assesses that action using its own obligation.

The object records the system ID, root source, original root numbers and
ordered attempts. Predicate projections also list retained fields, dropped
elements and any exact `recheck`. Projected attempts are local to their graph.
Their blockers describe transition defects, predicate evaluation errors,
exclusions or the state budget. After a projected defect or failed replay,
the validator can restore fields from omitted guards along the candidate
path and retry up to three times. Each round lists its retained and newly
added fields. For a projected safety PASS with transition-only blockers,
independent clean action coverage can clear the blockers. The attempt
lists those actions in `covered_transition_actions`.
A `Reachable` proof requires an error-free
covering scan and a concrete witness from each legal root. The check's trace
is concrete. `DeadActions` can use replayed action-entry witnesses alongside
exact results for other actions. Transition defects require independent
coverage after a firing witness. Each action has its own coverage obligation.
A supporting writer's speculative defect stays in that projection, and the
writer's own obligation decides whether there is a system diagnostic. The
validator uses exact action slices when it cannot certify coverage. DeadActions
can also establish a firing with a bounded concrete search prefix. NoDeadEnd
can prove recovery on a projection when every state has a rank leading to the
goal through intact actions. Uncertified results and dead-end witnesses use the
exact recovery path.

`slice` describes an exact slice and may be absent for a projection-decided
check. `states_explored` is always present and can count the smaller proof graph
or an exact graph already explored for diagnostic coverage. Attempt counts
describe the graphs used by the proof itself. For
`DeadActions`, `states_explored` sums the distinct graphs used to assess
actions, which depends on the coverage and graph reuse strategy. A smaller
proof can complete within the state budget when the exact slice would cap,
provided the required coverage also completes in a full run. `--no-slice`
uses the whole model. TLC checks exact graphs.

**0.1.0:** a `tlc.transition_defect` finding is retained in the affected
query or invariant's `findings` and repeated in `exploration`. The first occurrence
attributes the defect to that check; the second makes the aggregate run FAIL
(exit 1), even if the target itself stays INCONCLUSIVE because TLC stopped at the
transition defect. This applies to both full and selected checks. These are two
report locations for the same defect, not evidence of two distinct bugs.
Concatenating sections or adding compact group counts does not produce a unique
defect count; the report does not provide global diagnostic identities.

An empty reachable prefix is rendered as `(initial state) → paint`, including
the attempted action. Non-empty prefixes keep their action sequence. The defect
path is diagnostic text, not a proved witness or counterexample for the target:
`trace` retains the blocking finding and aggregate FAIL while the target can
remain INCONCLUSIVE with no property witness or state trace.

#### Compact findings

Since 0.0.7, `check --format json --compact` returns `analint.check.compact/v1`. Within
each finding list, entries are grouped by `code`, `severity` and `expected`.
Each group reports its full `count` and up to three `examples` in report order.
Each example contains the original `location` and `message`. An `expected: true`
group represents intended rejections in a passing negative scenario.

Both formats include the validation verdict, summary and individual check
results, and use the same exit codes. Use `check --format json` for every
individual finding in `analint.check/v1`.

#### Finding codes

Since 0.0.6, every finding is
`{"severity", "code", "location", "message"}`. Classify findings by `code`,
not by `message`: wording may change, but within `analint.check/v1` a code is
never renamed or reused for another kind. New codes may be added, so treat an
unknown code by its `severity`. Exploration artifacts (`analint.exploration/v1`)
carry the same codes.

A finding inside a **passing** `Expect.FAIL` scenario that gives the rejection
reason has `"expected": true`. Its `ERROR` severity is preserved, but it is the
intended outcome, not an actionable failure. The key is absent everywhere else,
and it never appears in a failed scenario. Verdicts and statuses are unchanged.

| Prefix | Codes |
| --- | --- |
| `finding.` | `finding.unclassified` (the default for findings constructed without a code via `analint.reporter.Finding`) |
| `structural.` | `structural.empty_model`, `structural.missing_id`, `structural.duplicate_id`, `structural.duplicate_class`, `structural.unregistered`, `structural.stale_reference`, `structural.invalid_entry`, `structural.scope_misuse`, `structural.unbound_variable`, `structural.effect_conflict`, `structural.unknown_field`, `structural.lifecycle_unattached`, `structural.terminal_transition`, `structural.unreachable_lifecycle_state`, `structural.no_scenarios`, `structural.missing_given`, `structural.duplicate_given`, `structural.empty_flow`, `structural.payload_binding`, `structural.payload_type_mismatch`, `structural.conflicting_roots`, `structural.invalid_initial` |
| `model.` | `model.unloaded_file`, `model.orphan`, `model.canonical_initial_error` |
| `transition.` (rejections) | `transition.pre_failed`, `transition.pre_not_applicable`, `transition.presence_rejected`, `transition.terminal_locked` |
| `transition.` (model defects) | `transition.evaluation_error`, `transition.field_constraint`, `transition.undeclared_lifecycle_edge`, `transition.postcondition_violated` |
| `exploration.` | `exploration.action_excluded`, `exploration.unsupported_value` |
| `invariant.` | `invariant.violated`, `invariant.evaluation_error`, `invariant.not_checked` |
| `scenario.` | `scenario.expected_rejection`, `scenario.not_rejected`, `scenario.then_failed`, `scenario.then_evaluation_error`, `scenario.event_not_emitted` |
| `flow.` | `flow.step_not_run`, `flow.invariant_violated`, `flow.checkpoint_failed`, `flow.checkpoint_evaluation_error`, `flow.event_not_emitted` |
| `query.` | `query.invalid`, `query.invalid_root`, `query.invalid_state`, `query.evaluation_error`, `query.vacuous`, `query.witness`, `query.holds`, `query.reached_forbidden`, `query.not_reachable`, `query.property_violated`, `query.dead_end`, `query.goal_unreachable`, `query.dead_actions`, `query.not_assessed`, `query.undecided`, `query.initial_state` |
| `check.` | `check.budget_exhausted`, `check.excluded_actions` |
| `tlc.` | `tlc.unavailable`, `tlc.no_invariant_form`, `tlc.not_exported`, `tlc.failed`, `tlc.transition_defect`, `tlc.decided` |

## show

```bash
analint show -p .
analint show action -p .
analint show action resolve -p .
analint show query -p .
analint show query can_archive -p .
analint show entity Ticket -p .
analint show lifecycle Ticket.status -p .
analint show action redeem_code -p examples/oauth/
```

`show [KIND] [NAME] --path PATH` always returns JSON. Without arguments it
returns the `analint.overview/v1` model inventory. With a kind it lists ids;
with a kind and name it returns details using `analint.show/v1`.

Detailed kinds are `entity`, `event`, `invariant`, `query`, `action`, `lifecycle`,
`flow`, `scenario` and `contract`. Singular and plural kinds work for id lists,
including `show query` / `show queries` and `show entity` / `show entities`.

Since 0.0.6, `show query ID` returns `kind: "query"`, the query
`type`, `label`, effective `max_states` (query override or inherited Spec budget), `predicate` and `goal`. The predicate is
null for NoDeadEnd/DeadActions; the goal is populated only for NoDeadEnd. This
describes the check without running it; use `check` for a verdict and `trace`
for a witness or counterexample.

The `roots` object describes the query's starting relation. Its `source` is
`canonical` when the query inherits `Spec.initial` or entity defaults, and
`query` when it declares its own `given`, `given_any` or `initial`. It includes
rendered `given` / `given_any` snapshots (`Absent(ref)` preserves absence) and
the effective `initial` relation: `vary`, `where`, `given`, `max_candidates`.
A null `initial` means defaults plus any given snapshots. Candidate states are
not enumerated and the relation is not validated by inspection.

Since 0.0.6, `show action FAMILY_ID` accepts an unexpanded
parameterized family name, such as `redeem_code` from `oauth-protocol`. It
returns `kind: "action_family"`, the declaration's shared
`pre`/`effect`/`post`/`emits`, parameter `params` with rendered domain values,
`where`, `variant_count`, concrete `variants` ids and related scenario/flow ids.
Only variants already in the model are listed, after static `where` filtering;
an empty family remains inspectable with zero variants. This does not expand
or execute the family again. A concrete action id keeps `kind: "action"` and
its existing detail format, taking precedence over a family name if both match.

## affects

```bash
analint affects Queue.open_tickets -p .
analint affects Ticket -p .
analint affects resolve -p .
```

`affects TARGET --path PATH` returns `analint.affects/v1`. Targets are fields
(`Entity.field`), entity/event names or action ids. Inspect readers, writers,
constraints and scenario coverage before changing the model.

Since 0.0.5, field writers include `Create` initialization, including omitted
fields taking their defaults. Such entries carry `initialization: "explicit"` or `"default"`
and render the `Create(...)` operation. `Delete` changes presence rather than
assigning field values. Entity `written_by` includes both creation and deletion.

Reads cover pre/post predicates, effect right-hand sides, old Add/Subtract
targets, emitted payload expressions, lifecycle transition source states and
terminal locks. These are static dependencies across possible worlds, not a
claim that every expression executes in every state. Payload/post references
describe next-state dependencies; they need not read the old value of a field
the same action assigns. World invariants are listed separately from action reads.

Action reports add `presence_reads` (instance labels) and `presence_writes`
(`{"instance": "Item['a']", "present": true|false}`). These cover explicit
Present predicates, scoped field reads, finite quantifier/aggregate membership
and the implicit guards for modifying/creating/deleting a slot. Entity reports
add `presence_read_by` and `presence_written_by`; their ordinary reader/writer
lists also include presence dependencies. Field reports remain about field
values. `Key(ref)` alone reads neither fields nor presence; quantification over
keys still reads domain membership. Expression-based event bindings and their
scenarios are included. These are additive fields in the existing v1 schemas.

**0.1.0:** if a `--what-if` file cannot be loaded, both `explore` and
`trace` return a load error (exit 3), just as `check` rejects that preparation.
They do not return an artifact for the unchanged base model.

## trace

```bash
analint trace can_archive -p .
analint trace can_archive -p . --format json
analint trace resolved_leaves_no_open_ticket -p .
```

`trace PROPERTY_ID --path PATH` returns a query witness or invariant
counterexample with state changes. Options are `--format terminal|json`,
`--what-if FILE.py` and `--no-slice`. 0.1.0: `--max-states`, `--cache`,
`--tlc` and `--tlc-timeout` accept the same invocation settings as check.

JSON uses `analint.trace/v1`, with `query` or `invariant` identifying the property,
its `status`, the root, `steps` and `final_state`. A property without a witness
returns `witness: null` and an explanation. The command follows `check`'s slice
and budget decisions; use `--no-slice` for the whole model. 0.1.0: pass the
same budget/cache/TLC options used for the selected check. A trace call selects
that one property plus the same supporting invariant proofs; it does not inherit
settings from a previous process. `query:ID` and `invariant:ID` disambiguate.
`trace` accepts only queries and invariants: a `flow:ID` selector copied from
`--check` is not a valid trace target and returns an unknown-property error.
Run that flow with `check --check flow:ID` instead.

0.1.0 trace metadata includes `selection`, `verification_verdict` and
exploration `findings`. Unrelated findings and their bounded coverage appear in
`model_findings` and `model_coverage`, with the same verdict separation as check.
A property's status does not override failures in its supporting verification. TLC checks defect assertions only for the selected
proof's dependency actions; all exported actions and legal-state constraints stay
in the transition system. When TLC decides the property, `backend: "tlc"` and
`action_trace` retain its parsed witness (null means no witness; [] can mean the
initial state). TLC state snapshots are not available: `state_trace_available`
is false, `root` is null, `steps` is empty and `final_state` is empty. The tool
does not substitute a native rerun or invent state changes. Native traces retain
the existing state-diff representation. A `query.invalid_root` failure includes
an explanation in `message`: the root is invalid under model invariants and was
not expanded. Native traces retain that root with zero steps; TLC includes its
number and explanation without state snapshots.

`NoDeadEnd` uses `query.invalid_state` when its chosen dead-end witness has
explicit invariant-violation or invariant-evaluation-error provenance. Its
message names the invariant ids and explains that the state was not expanded;
recovery from that invalid state was not assessed. The query remains FAIL and
the invariant diagnostic remains visible separately. Native `trace` retains the
same witness and steps and includes this explanation in `message`. Legal dead
ends keep `query.dead_end`; no-goal and incomplete-graph results retain their
existing diagnostics. Attribution uses finding-to-state indices, including on
warm cache reads, never diagnostic prose or a matching invariant id alone.

Successful trace retrieval is an inspection operation. Its process exit code
does not replace the property's `status` or a `check` verdict.

## explore

```bash
analint explore .
analint explore . --format json
analint explore . --query can_archive --format json --include-graph
```

`explore [PATH]` explores the **whole model**, starting from canonical roots or
the roots of `--query ID`. It accepts `--what-if FILE.py` and
`--format terminal|json`. `--include-graph` includes the nodes and edges in JSON;
the default is a compact summary.

The `analint.exploration/v1` artifact includes `source`, `completeness`, `summary`,
`findings` and `graph`. `graph: null` can mean output was intentionally omitted;
it does not by itself mean the exploration was incomplete. Read `completeness`
separately. The artifact's content-derived node/edge ids are stable across
equivalent runs.

Like trace, explore is an inspection operation; use `check` as the CI verdict
gate. Explore does not have the check command's `--max-states`, `--cache`,
`--tlc` or `--no-slice` switches.

## Hypothesis workflow

Use the same shared entity classes in your hypothesis and spec. Packaged models
use qualified imports, as shown in the [tutorial](getting-started.md#test-a-proposed-rule-without-changing-the-model).

```bash
analint show -p path/to/spec
analint affects Entity.field -p path/to/spec
analint check path/to/spec --what-if hypothesis.py --format json
# Apply the accepted change to the spec, then check again.
analint check path/to/spec --strict
```

`--what-if` merges objects without editing the entry point or permanently
changing its cached root. After applying a hypothesis, list new behaviour on
Spec or an imported Contract; normal module imports do not register it.

## Exit codes

The following table applies to **check**:

| Code | Meaning |
| --- | --- |
| `0` | Effective PASS |
| `1` | FAIL: findings, failed scenarios/flows/properties, or strict warnings |
| `2` | CLI usage error, such as an invalid option or format |
| `3` | Spec failed to load or no root spec was found |
| `4` | INCONCLUSIVE, including an unchecked invariant preventing PASS |

For show, affects, trace and explore, a successful response means the inspection
operation ran; inspect the returned data to interpret verification results.
Machine-readable operation errors use `analint.error/v1` where supported.

## CI and local development

For an installed release, gate your spec with:

```bash
analint check path/to/spec --strict --format json
```

Pin the analint version and retain both the exit code and report. Do not turn
code `4` into success without an explicit policy for unresolved properties.

From a repository checkout, the documentation is checked with:

```bash
uv run --frozen pytest tests/test_documentation.py \
  tests/test_fixed_initial.py::test_fixed_roots_across_check_explore_and_trace \
  tests/test_keys.py::test_key_verdicts_traces_artifacts_and_cache_agree
uv run --frozen --group docs mkdocs build --strict
```

The docs workflow performs these checks for pull requests and main-branch
pushes before its main-branch-only deployment.
