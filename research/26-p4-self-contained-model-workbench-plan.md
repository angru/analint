# P4 implementation plan: self-contained model workbench

**Date:** 2026-06-15

## Goal

Turn the existing bounded verifier into a complete workbench for understanding
and debugging non-trivial models without relying on another verifier.

The transition semantics and the state graph already exist. P4 makes their
result stable, inspectable and measurable:

```text
Python spec
  -> validated model
  -> canonical/query-specific exploration
  -> versioned exploration artifact
  -> compact CLI/MCP diagnostics
  -> state-diff witness traces
```

P4 does not add a new verification primitive. It improves the correctness,
observability and practical scale of the current bounded-reachability engine.

## Preconditions discovered during planning

P4 must not stabilize an artifact over type boundaries that are currently
misrepresented to users.

The initial audit found:

- normal `uv run ty check` checks `src` only and passes;
- checking representative spec files directly currently produces 27
  diagnostics;
- the checker sees both instance access (`wallet.balance`) and class-level DSL
  access (`Wallet.balance`) as `int`. The first is the intended domain view; the
  second is a symbolic reference to an int-valued field at runtime.
  Consequently `Wallet.balance >= 0` is inferred as `bool` although the DSL
  constructs a `Predicate`;
- lifecycle declarations are statically reported as assigning
  `Lifecycle[State]` to `State`;
- parameter fields are not accepted as writable effect targets;
- `src` contains 12 `type: ignore[override]` and 9
  `type: ignore[attr-defined]` suppressions;
- examples contain 91 inline `noqa` comments, of which 89 are E712 suppressions
  for intentional boolean DSL comparisons;
- `invalid-method-override` and `ANN401` are ignored globally;
- no example has its own README;
- the root README lists only six of the ten example specs;
- `examples/play.py` is currently broken: it imports `_apply_effects` from its
  old location, duplicates transition semantics, and still describes the shared
  kernel as future work;
- the characterization snapshot records actual behavior but does not explain
  which failures and warnings are intentional.

The E712 comments do not by themselves prove a runtime type defect: an embedded
DSL intentionally overloads equality. Nor does the dual class/instance behavior
mean authors should see the private `FieldDescriptor` implementation. The
declaration `balance: int` is valuable domain documentation, and
`wallet.balance` should be an `int`. The open question is whether static tooling
can also model class-level `Wallet.balance` as a public symbolic
`FieldRef[int]`, without making the authoring syntax worse. P4.0 investigates
that trade-off; it must not assume in advance that the existing syntax is wrong
or mechanically replace domain types with descriptor types.

The runtime mechanism is already correct and is not a P4.0 implementation task:
`EntityMeta` replaces every annotated field, including annotation-only fields,
with a `FieldDescriptor` after class creation. `Field(...)` supplies constraints
and a default through `FieldSpec`; it is not required to enable the descriptor.
`FieldDescriptor` already overloads comparison and arithmetic operators to build
`Predicate`/`Expr` nodes. Do not reimplement these operators or add a second
conversion path. The mismatch exists because ordinary static analysis reasons
from the source annotation before this metaclass transformation.

## Decisions fixed before implementation

1. analint remains self-contained. The checked Quint model is comparison
   evidence, not a backend architecture.
2. The artifact describes one concrete exploration run. It is not a serialized
   `Spec`, normalized model IR or promise that arbitrary Python can be exported.
3. `analint check --format json` stays compact. Full graphs are opt-in because a
   small model already produces thousands of nodes and edges.
4. The existing `validator.explorer.Exploration` remains an internal mutable BFS
   structure. Public JSON must not expose Python classes, `InstanceRef`,
   `StateKey`, contexts, object identities or `repr()` of synthetic modules.
5. Completeness is independent of verdict. Represent it as:

   ```json
   {
     "complete": false,
     "reasons": ["capped", "excluded-semantics"]
   }
   ```

   Reasons are a list because both conditions can hold at once.
6. State and edge identity must be deterministic across processes. Never use
   Python `hash()`, object identity or discovery order as an external ID.
7. Timing is informational and never a CI assertion. Structural content,
   completeness, counts and graph hashes remain regression-testable.
8. No visualization UI, public model IR, Rust rewrite, temporal logic, event
   pool, semantic diff or publication work belongs in this phase.

## Target artifact

The first schema is `analint.exploration/v1`.

```json
{
  "schema": "analint.exploration/v1",
  "spec": {"id": "oauth", "version": "0.6.0"},
  "source": {"kind": "canonical", "query": null},
  "completeness": {
    "complete": true,
    "reasons": [],
    "max_states": 10000
  },
  "summary": {
    "roots": 1,
    "states": 1169,
    "edges": 2256,
    "max_depth": 6,
    "dead_ends": 0,
    "self_loops": 0,
    "branching": {"min": 0, "mean": 1.93, "max": 8},
    "fired_actions": [],
    "edge_count_by_action": {},
    "excluded_actions": {}
  },
  "findings": [],
  "graph": {
    "roots": [{"index": 1, "node": "sha256:..."}],
    "nodes": [],
    "edges": []
  }
}
```

Compact projections set `graph` to `null` and add an explicit
`graph_omitted` reason. Output truncation is not an exploration-incompleteness
reason.

### Node

```json
{
  "id": "sha256:<canonical-state-digest>",
  "depth": 2,
  "parent_edge": "sha256:<edge-digest>",
  "state": {
    "AuthCode['c1'].state": "CodeState.ISSUED",
    "AuthCode['c1'].@present": true
  }
}
```

- State keys use `context_key_label`.
- Values are JSON-native scalars. Enum values use the stable
  `TypeName.MEMBER` spelling.
- State maps are sorted before canonical JSON encoding.
- Node IDs are SHA-256 digests of canonical JSON state content.
- `parent_edge` identifies the BFS shortest-path tree; it is not the only
  incoming edge.

### Edge

```json
{
  "id": "sha256:<edge-digest>",
  "source": "sha256:<state-digest>",
  "target": "sha256:<state-digest>",
  "action": "redeem_code(...)",
  "family": "redeem_code",
  "binding": {
    "code": "AuthCode['c1']",
    "token": "Token['t1']"
  },
  "changes": [
    {
      "field": "AuthCode['c1'].state",
      "before": "CodeState.ISSUED",
      "after": "CodeState.REDEEMED"
    }
  ]
}
```

- Keep the concrete action ID because it is already the executable transition
  identity.
- Preserve the family and structured binding separately; consumers must not
  parse the action ID.
- Binding metadata is internal to a bound `Action`. Add it as a Pydantic private
  attribute, not a new author-facing constructor field.
- Changes use the kernel's state-diff semantics. Do not re-run `step()` while
  rendering an artifact.

## Implementation sequence

Each checkpoint is a separate commit. Do not combine later CLI, benchmark or
visualization work into the artifact-core commit.

### P4.0a — DSL and type-boundary audit

**Outcome:** the project has an explicit model of the DSL's dual view:
domain-valued instance access versus symbolic class-level access, plus a tested
decision on how much of that distinction static tooling should expose.

This is an audit and design gate, not a mandate to eliminate every `Any`.
Dynamic loading and heterogeneous state necessarily retain some dynamic
boundaries. The goal is to make each boundary deliberate, local and validated.

Produce a type matrix covering runtime truth, author-facing domain meaning and
candidate static representations:

| Surface | Author-facing meaning | Runtime role | Candidate static role |
|---|---|---|
| `wallet.balance` | current balance value | domain value `T` | `T` |
| `Wallet.balance` | reference to an int-valued field | field-reference object | ideally `FieldRef[T]`; may require syntax/tooling support |
| scoped class field | reference to one slot's field | field-reference object | same symbolic reference |
| `Param` / `ParamField` | finite symbolic value/reference | symbolic operand | generic symbolic operand |
| `BoundField` | quantified symbolic reference | symbolic operand | generic symbolic operand |
| arithmetic expression | derived domain value | AST node | `ValueExpr[T]` |
| class-level comparison | domain rule | predicate AST | ideally `Predicate`, not ordinary `bool` |
| effect target/value | field update relation | writable ref and compatible value | same `T` where practical |
| evaluation context | internal state snapshot | heterogeneous runtime map | internal alias, never public JSON |

Representative Pylance diagnostics currently come from two independent
mechanisms:

1. **Metaclass opacity.** Pylance sees the source annotation on class access, so
   `Wallet.balance >= Order.total` is inferred as `bool` and `Order.status` is
   inferred as `OrderStatus`, even though `EntityMeta` replaces both attributes
   with symbolic field descriptors at runtime.
2. **Mutable collection invariance.** Even when each element is a valid subtype,
   `list[Set | Subtract]` is not assignable to `list[Effect]`, and a list of
   concrete predicate node types is not necessarily assignable to
   `list[Predicate]`.

The second issue is an input-typing problem, not evidence that the effect classes
have the wrong inheritance. Address it separately without widening the DSL AST
to `Any` or weakening runtime validation.

### Approved authoring decision

Keep annotation-first domain declarations such as `balance: int`.

This is the intended public syntax, not a temporary compatibility mode. Instance
access remains honestly typed and domain-readable; class access is the embedded
DSL's symbolic runtime view. P4 must not replace it with descriptor-first
declarations, require a parallel `Wallet.fields.balance` namespace, or expose
`FieldDescriptor` to authors merely to satisfy a static checker.

Consequences:

- limited false positives for class-level DSL expressions are an accepted
  checker boundary;
- P4.0 should document a narrow Pylance/Pyright and PyCharm inspection policy
  for spec files rather than disabling Python analysis project-wide;
- constructor typing and collection variance remain valid improvements because
  they do not compromise the declaration syntax;
- checker plugins or generated stubs are deferred unless a low-maintenance
  prototype can preserve the exact syntax without duplicating model semantics.

Tasks:

1. Inventory every symbol exported from `analint.__init__` and classify it as:

   - core authoring primitive;
   - advanced authoring primitive;
   - predicate/expression/effect AST;
   - verification query;
   - result/reporting type;
   - compatibility alias;
   - implementation detail that should not be public.

   Record the result in `research/27-dsl-type-boundary-audit.md`. The audit must
   state the intended minimal DSL rather than treating the current export list
   as automatically correct.
2. Add direct typecheck probes for documented authoring forms. During the audit,
   preserve the current diagnostics as evidence rather than suppressing them;
   `[tool.ty.src] include = ["src"]` currently excludes the real user
   experience.
   Include both annotation-only fields and constrained `Field(...)` fields to
   prove that their runtime DSL behavior is already identical. Include
   Pylance/Pyright inference for representative real-world `Action(...)`
   declarations, not only `ty` probes.
3. Prototype negative probes for obvious mismatches: setting an integer field to
   an unrelated Enum, a non-predicate in `pre`, and an invalid effect target.
4. Include constructor typing in the probes: missing/unknown/wrongly typed
   `Entity` and `Event` fields. Evaluate `dataclass_transform` on `EntityMeta`
   rather than assuming dynamic `**kwargs` is unavoidable.
5. Inventory every `Any`, `type: ignore`, global rule suppression and inline
   `noqa`, classifying it as:

   - embedded-DSL protocol conflict;
   - dynamic loader/context boundary;
   - missing closed AST union/protocol;
   - checker limitation;
   - intentional negative test;
   - accidental imprecision.

6. Design how the repeated `Expr` `attr-defined` suppressions would be replaced:
   a closed expression protocol/base carrying typed `left`/`right`, or explicit
   matching on concrete expression nodes. Do not choose by patch size alone.
7. Review broad public containers such as `Scenario.then`, query `given`,
   `Initial.vary`, predicate operands and context dictionaries. Replace `Any`
   with closed unions/protocols where the accepted runtime set is already known.
   Keep runtime validation for all of them.
8. Review constructor variance. Inputs such as `list[_Implies]` should be
   accepted where a sequence of `Predicate` is valid; public constructors should
   not require callers to widen local variables manually because `list` is
   invariant. Compare covariant read-only input annotations with explicit typed
   constructor signatures while preserving list normalization and Pydantic
   serialization behavior at runtime.
9. Identify the exact AST/ref classes that require the intentional
   `__eq__ -> Predicate` override and propose a local suppression strategy.
10. Preserve annotation-first declarations and measure the exact diagnostics
    that remain in Pylance/Pyright and PyCharm. Prototype only tooling approaches
    that preserve the syntax and do not duplicate model semantics; otherwise
    document a narrow inspection policy for spec files.

11. Evaluate `Lifecycle`, `Scope`/`InstanceRef`, `Bound`, and `Param` in the same
   prototype. Fixing only singleton fields would leave the advanced DSL
   untyped.
12. Decide how boolean predicates avoid 89 per-line E712 suppressions:

   - documented file-level lint policy for specs;
   - a typed predicate helper;
   - another solution that does not weaken normal Python linting globally.

13. Write the selected contract into the audit document before migration. Include
   compatibility and migration cost; do not silently rewrite all examples.
14. Select at least one CLI-runnable checker whose behavior is close enough to
    the supported editor experience to make regressions testable. `ty` alone is
    insufficient if Pylance/Pyright remains a supported authoring surface.

P4.0a acceptance criteria:

- public primitive/advanced/internal boundaries are documented;
- the audit reproduces the current class-field/predicate/lifecycle/param
  diagnostics;
- type probes cover singleton fields, scopes, bounds, params and constructors
  while preserving annotation-first declarations;
- `wallet.balance: T` and domain-readable entity declarations are preserved;
  private `FieldDescriptor` is not exposed as domain data;
- all current `Any`/ignores are listed by category;
- the recommended option includes compatibility and migration costs;
- runtime structural validation remains fail-closed because static typing is
  advisory and can be bypassed.

Review checkpoint: stop after the type audit and inspection-policy proposal.
Changing field declaration syntax is outside the approved P4 scope.

Commit checkpoint:

```text
P4.0a: audit DSL type boundaries and add authoring type probes
```

### P4.0b — Approved DSL typing policy

**Outcome:** retain the current annotation-first syntax, document its static
limits, and improve internal/constructor typing without changing the authoring
model.

Tasks:

1. Implement the approved annotation-first field/class-vs-instance typing policy
   without exposing private descriptor implementation names to spec authors.
2. Apply it consistently to `Lifecycle`, `Scope`/`InstanceRef`, `Bound`,
   `Param`/`ParamField`, expressions and effects.
3. Add positive fixtures under `tests/typecheck/` for every documented authoring
   form.
4. Add machine-checked negative fixtures for missing/unknown/mistyped
   Entity/Event fields, incompatible effect values, invalid targets and
   non-predicate conditions. Use the checker's supported diagnostic assertions
   or a dedicated test harness; do not leave intentionally failing files in the
   normal green source set.
5. Replace the repeated `Expr` `attr-defined` suppressions with the approved
   closed protocol/base or concrete-node traversal.
6. Replace broad public `Any` containers with the approved closed unions where
   the runtime set is known.
7. Resolve input variance so valid predicate and effect subclasses typecheck
   naturally. Keep the distinction between accepted constructor input types and
   mutable runtime storage explicit.
8. Remove the global `invalid-method-override` exemption and keep any unavoidable
   suppression local to intentional DSL operator implementations.
9. Apply the chosen E712 policy consistently; remove per-line noise if the
   policy permits it.
10. Document editor/checker setup for spec files without disabling useful Python
    analysis for the rest of the project.
11. Add both implementation and public-authoring checks to the normal gate:

    ```bash
    uv run ty check
    uv run ty check <explicit public typecheck fixtures>
    ```

P4.0b acceptance criteria, interpreted according to the approved policy:

- documented public DSL examples pass the selected authoring check without
  unexplained diagnostics; this may be a dedicated DSL-aware check rather than
  pretending ordinary Python inference understands class-level expressions;
- negative type fixtures fail for the intended reason;
- Entity/Event constructor probes cover missing, unknown and mistyped fields;
- no global `invalid-method-override` exemption;
- AST traversal has no `attr-defined` ignores;
- remaining `Any`/ignores are justified in the audit;
- all runtime, characterization and example tests remain green.

Commit checkpoint:

```text
P4.0b: implement the approved typed field/reference contract
```

If this requires a broad DSL migration, finish it and return all examples/tests
to green before starting the artifact schema.

### P4.0c — Example intent contracts

**Outcome:** every example has a human explanation and a machine-checked
expected outcome, separate from the characterization snapshot.

Add `examples/expectations.toml` with one entry for every directory containing a
`spec.py`:

```toml
[coin]
verdict = "FAIL"
exit_code = 1
failed_queries = ["supply_never_overflows"]
warning_locations = []
```

Each entry records:

- expected overall verdict and CLI exit code;
- intentionally failing scenario/query/invariant/flow IDs;
- expected warning locations;
- whether the example is deliberately broken or expected clean;
- optional source/research reference.

Add `examples/<name>/README.md` for all ten current specs using one template:

1. purpose and external source, if any;
2. modeled scope and explicit omissions;
3. important entities/actions/properties;
4. exact command;
5. expected verdict, intentional failures and warnings;
6. what a behavioral change in this example means;
7. related research.

Update the root README table to include every example:

- `branch_protection`
- `cloak`
- `coin`
- `ecommerce`
- `fulfillment`
- `mafia`
- `oauth`
- `sunless_crypt`
- `taskboard`
- `trollbridge`

Add `tests/test_example_expectations.py`:

1. discover every `examples/*/spec.py`;
2. require exactly one manifest entry and one local README per example;
3. validate each example and compare verdict, failed IDs and warning locations;
4. invoke or derive the documented exit code;
5. fail if the root README omits an example;
6. fail on stale manifest entries;
7. keep exact graph/state details in `tests/snapshots/examples.json`.

Audit shared example tooling as part of the same checkpoint:

1. document `examples/play.py` from the root README and the
   `sunless_crypt/README.md`;
2. replace its hand-written pre/effect/clamp path with `kernel.step` so the
   playable example cannot drift from scenario/flow/explorer semantics;
3. remove stale text saying the transition kernel is only planned;
4. add a non-interactive smoke test that loads the game and executes a fixed
   choice sequence without private-import failure;
5. decide and document whether the runner enforces world invariants in addition
   to transition legality;
6. fail the example-contract test if a documented helper script no longer runs.

Current intentional outcomes that must seed the manifest:

- `coin`: `FAIL`, query `supply_never_overflows`;
- `trollbridge`: `FAIL`, queries `hp_never_negative` and `no_softlock`;
- `ecommerce`: `PASS` with warning at `action:checkout`;
- `taskboard`: `PASS` with warnings at `action:move_card`,
  `action:send_notification`, and `action:read_notification`;
- `sunless_crypt`: `PASS` with 13 missing-scenario warning locations;
- all other examples: currently `PASS` with no warnings.

Do not automatically bless changed output. When this test fails, either fix a
regression or update the manifest and README with a reviewed explanation.

Commit checkpoint:

```text
P4.0c: make example intent executable and document every example
```

### P4.1 — Artifact core

**Outcome:** a deterministic, fully serializable DTO can be built from one
existing `Exploration`.

Implementation:

1. Add internal artifact DTOs and serialization in
   `src/analint/reporter/exploration_artifact.py`.
2. Add a converter in `src/analint/validator/artifact_builder.py`.
3. Add canonical scalar/state/diff rendering helpers. Reuse
   `context_key_label`, presence semantics and `all_fields`; do not duplicate
   field discovery.
4. Preserve structured parameter bindings on concrete actions through a private
   `Action` attribute populated by `bind_action`.
5. Compute node IDs, edge IDs, depths, BFS parents, roots, action counts,
   branching statistics, dead ends and completeness.
6. Keep `Exploration.states`, `edges`, `parents` and `roots` unchanged in this
   checkpoint. The converter adapts them; it does not rewrite BFS.
7. Do not export the Python DTOs from `analint.__init__` yet. The stable contract
   is the versioned JSON shape.

Required tests in `tests/test_exploration_artifact.py`:

- repeated runs and different processes produce identical artifact JSON;
- output contains no classes, `InstanceRef`, `StateKey`, Enum objects or
  non-string dictionary keys;
- scalar, Enum, `None`, presence, `Create` and `Delete` states serialize;
- multi-root exploration preserves all distinct root indices;
- parameterized actions expose family and structured bindings;
- self-loops and duplicate-target edges remain visible;
- shortest-parent depth and state diffs are correct;
- `capped` and `excluded-semantics` can appear together;
- complete exploration has `complete=true` and no reasons;
- OAuth summary remains 1169 states / 2256 edges.

Regression gates:

```bash
uv run pytest tests/test_exploration_artifact.py -q
uv run pytest tests/test_characterization.py -q
uv run pytest -q
```

Commit checkpoint:

```text
P4.1: add deterministic exploration artifact core
```

### P4.2 — Exploration service and compact CLI/MCP surface

**Outcome:** a user or agent can request a canonical or query-specific
exploration without receiving an accidental full-graph dump.

Implementation:

1. Extract the minimum shared model-preparation path from `validate()`:
   loading, what-if application, unloaded-file findings and structural
   validation. Validation and exploration must use the same prepared `Spec`.
2. Add an application service:

   ```python
   explore_path(path, *, query_id=None, what_if=None) -> ExplorationArtifact
   ```

3. With no query, explore the canonical initial relation and
   `Spec.max_states`.
4. With `query_id`, use exactly that query's `given`, `given_any`, `initial` and
   `max_states`. Extract and reuse initial-source resolution from `run_query`;
   do not implement a second interpretation.
5. Reject unknown query IDs and structurally invalid/unbuildable models with a
   structured error. Never return an empty successful artifact.
6. Add CLI:

   ```bash
   analint explore PATH
   analint explore PATH --query QUERY_ID
   analint explore PATH --format json
   analint explore PATH --format json --include-graph
   analint explore PATH --what-if patch.py
   ```

7. Terminal output is summary-first: completeness, roots/states/edges/depth,
   branching, fired/dead/excluded actions and findings.
8. JSON defaults to the compact projection. `--include-graph` emits all nodes
   and edges; it never silently truncates.
9. Add MCP `explore` using the same service. MCP defaults to compact output.
   `include_graph=true` requires a caller-provided `max_graph_states`; if the
   graph is larger, return the complete summary with `graph=null` and an
   explicit output-omission reason.
10. Keep `check_spec`, CLI `check` JSON and exit codes backward compatible.

Required tests:

- CLI canonical summary and JSON;
- CLI query-specific roots and budget;
- CLI/MCP what-if behavior;
- invalid query, load failure, structural failure and unbuildable initial;
- compact output omits graph explicitly;
- full output round-trips through `json.dumps`/`json.loads`;
- MCP graph guard does not misreport exploration completeness;
- `validate()` characterization is unchanged after model-preparation extraction.

Commit checkpoint:

```text
P4.2: expose canonical and query exploration through CLI and MCP
```

### P4.3 — State-diff witness traces

**Outcome:** every query witness can be read as states and changes, not only a
list of action IDs.

Implementation:

1. Preserve the internal witness `StateKey` in `QueryResult` without serializing
   that Python value.
2. Resolve it to the artifact node ID at the application-service boundary.
3. Add a `TraceArtifact` projection:

   ```json
   {
     "query": "no_token_to_wrong_client",
     "status": "FAIL",
     "root": {"index": 1, "node": "sha256:..."},
     "steps": [
       {
         "action": "issue_code(...)",
         "source": "sha256:...",
         "target": "sha256:...",
         "changes": []
       }
     ],
     "final_state": {}
   }
   ```

4. Add CLI:

   ```bash
   analint trace QUERY_ID -p PATH
   analint trace QUERY_ID -p PATH --format json
   ```

5. Add MCP `trace`. Both surfaces must report clearly when a passing property
   has no witness/counterexample.
6. Terminal traces show only changed fields per step plus the final relevant
   state. Do not repeat the full state at every step.
7. Preserve the existing `QueryResult.trace: list[str]` for compatibility.
   `check --format json` may add `witness_state` but must not embed the full
   graph.

Required tests:

- passing `Reachable` witness;
- failing `Unreachable`, `AlwaysHolds` and `NoDeadEnd` counterexamples;
- multi-root trace names its root;
- repeated action IDs still resolve the exact state path;
- self-loop trace;
- state changes for normal effects and presence flips;
- no-witness response is explicit and non-crashing;
- terminal and JSON render the same steps.

Commit checkpoint:

```text
P4.3: add state-diff query witness traces
```

### P4.4 — Scaling characterization before optimization

**Outcome:** engine work is driven by reproducible state-space families rather
than intuition or one story-shaped example.

Add generated in-memory model families under `scripts/`:

1. **Counter grid:** `N` independent bounded counters.
   Expected states: `(bound + 1) ** N`.
2. **Conserved transfer:** `N` accounts sharing a fixed number of units.
   Expected states: combinations with repetition for the chosen total.
3. **Workflow product:** `N` independent finite lifecycles.
   Expected states: `states_per_workflow ** N`.

The harness must:

- produce cases around 10², 10³, 10⁴ and 10⁵ reachable states;
- report states, edges, actions, roots, completeness, wall time, peak memory,
  time/state and bytes/state as JSON and a readable table;
- verify expected state counts for small/medium cases;
- run warmups and multiple repetitions, reporting median and minimum;
- record Python/platform metadata;
- remain informational, not a timing CI gate.

Baseline before optimization:

```bash
uv run python scripts/bench.py --json
uv run python scripts/bench_scaling.py --json
```

Optimization rules:

1. Profile before changing code.
2. One optimization per commit.
3. Run characterization and the full test suite after each change.
4. Record before/after measurements in this document.
5. Prefer semantic-neutral algorithmic work first: `deque`, precomputed state
   layout, avoiding repeated descriptor walks, action indexing.
6. Do not implement symmetry reduction or partial-order reduction without a
   separate semantic design and tests proving which traces/properties they
   preserve.
7. Stop when the measured target is met or the next improvement requires a
   normalized execution plan; do not start Rust/Numba by momentum.

Initial target, subject to baseline correction:

- complete 10⁴-state families comfortably in the normal edit/check loop;
- complete or honestly cap 10⁵-state families without pathological memory use;
- artifact summary overhead below 10% of exploration time;
- full graph serialization remains opt-in and is measured separately.

Commit checkpoints:

```text
P4.4a: add generated scaling characterization
P4.4b: optimize <measured bottleneck>
```

### P4.4a baseline (2026-06-16, CPython 3.14.5)

`scripts/scaling_models.py` (counter_grid, conserved_transfer, workflow_product)
+ `scripts/bench_scaling.py`. All families reproduce their closed-form counts
(`tests/test_scaling_models.py`). Timings are noisy/hardware-dependent — recorded
for trend, not as a gate.

| family | states | edges | t_min | µs/state | artifact % |
|---|---:|---:|---:|---:|---:|
| counter_grid (4,9) | 10 000 | 36 000 | 0.78 s | ~78 | 48% |
| conserved_transfer (5,20) | 10 626 | 177 100 | 5.1 s | ~484 | 37% |
| workflow_product (7) | 16 384 | 86 016 | 4.3 s | ~260 | 28% |

Findings that direct P4.4b:

1. **Throughput is edge-dominated, not state-dominated.** conserved_transfer's
   `send` expands to O(n²) bound actions, so its 10⁴-state case has 177k edges and
   is ~6× slower per state than the sparse counter grid. The cost is per-edge
   transition work, not per-state bookkeeping.
2. **The artifact build is 28–88% of exploration time** — far above the <10%
   *summary* target — because the full builder renders every state and computes a
   SHA-256 digest per node/edge. This confirms the review note on 4b5535d: compact
   and MCP-guarded output should NOT materialise the whole graph. The
   measurement-justified P4.4b is a **summary-only artifact path** that computes
   completeness/summary directly from the `Exploration` without rendering nodes,
   edges or digests; the compact CLI/MCP projections then use it.
3. 10⁴-state families complete in the edit/check loop (sub-second to a few
   seconds); the 10⁵ tier (`--full`) is runnable but slow — honest, not capped.

### P4.5 — Project-sized dogfood gate

**Outcome:** validate the workbench on a model larger than a tutorial, not add a
new language feature.

Select one externally documented system after P4.1–P4.3 are usable. The model
should have:

- at least three interacting entity types or scopes;
- at least ten meaningful actions;
- identity/provenance across objects;
- both positive reachability and negative safety properties;
- at least one dead-end or recovery question;
- a measured series of at least three requirement changes;
- a state space large enough to exercise artifact summaries and traces, ideally
  10³–5×10⁴ states without artificial padding.

Kubernetes ReplicaSet + ResourceQuota remains a strong candidate because it
adds reconciliation and resource competition. It is not preselected: choose the
domain whose public rules are clearest when this checkpoint starts.

For every change:

1. Run `show` and `affects`.
2. Test the proposed property through `--what-if`.
3. Record the model diff, state/edge delta and artifact summary.
4. Review the shortest state-diff witness.
5. Record authoring, diagnostic and scaling friction.

No new primitive is allowed during the first implementation attempt. If blocked,
record the missing guarantee and try an honest state-modeling alternative.
Reopen semantics only when the same limitation already appears in another real
model or makes the project impossible to model without distorting its rules.

Commit checkpoint:

```text
P4.5: validate the workbench on <external system>
```

## Review checkpoints

Stop for review after the P4.0a type prototype, P4.1, P4.3 and the P4.4
baseline.

The reviewer should answer:

1. Does the selected type contract make class and instance access honest without
   unacceptable DSL complexity?
2. Is the artifact deterministic and free of Python implementation identities?
3. Does completeness remain honest under caps and excluded actions?
4. Is the compact surface useful without loading the full graph?
5. Can a query counterexample be understood from state diffs alone?
6. Did any optimization alter states, edges, findings or shortest traces?
7. Did dogfooding reveal repeated semantic pain or only authoring/performance
   friction?

## Definition of done

P4 is complete when:

- the public DSL type contract is explicit and exercised by direct typecheck
  fixtures;
- every example has a README and machine-checked expected outcome;
- the versioned exploration artifact is deterministic and tested;
- canonical and query-specific exploration are available through CLI and MCP;
- query witnesses have state-diff traces;
- compact output is the default and full graphs are explicit;
- completeness is machine-readable and never conflated with output omission;
- generated scaling baselines exist and at least the measured low-risk
  bottlenecks have been addressed;
- one project-sized external model has been exercised through the complete
  agent workflow;
- all characterization and semantic-conformance tests remain green;
- no external verifier is required for any P4 acceptance criterion.
