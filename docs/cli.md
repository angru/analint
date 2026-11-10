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
charged to its first consumer, and invariant retries are included. Model
preparation and shared action coverage are excluded. Summing these timings does
not give total command time.

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
| `query.` | `query.invalid`, `query.evaluation_error`, `query.vacuous`, `query.witness`, `query.holds`, `query.reached_forbidden`, `query.not_reachable`, `query.property_violated`, `query.dead_end`, `query.goal_unreachable`, `query.dead_actions`, `query.not_assessed`, `query.undecided`, `query.initial_state` |
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
`type`, `label`, declared `max_states`, `predicate` and `goal`. The predicate is
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

## trace

```bash
analint trace can_archive -p .
analint trace can_archive -p . --format json
analint trace resolved_leaves_no_open_ticket -p .
```

`trace PROPERTY_ID --path PATH` returns a query witness or invariant
counterexample with state changes. Options are `--format terminal|json`,
`--what-if FILE.py` and `--no-slice`.

JSON uses `analint.trace/v1`, with `query` or `invariant` identifying the property,
its `status`, the root, `steps` and `final_state`. A property without a witness
returns `witness: null` and an explanation. The command follows `check`'s slice
and budget decisions; use `--no-slice` for the whole model. Adjust the model's
budget for a larger trace exploration; trace has no `--max-states` option.

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
