# Verification concepts

A specification is a model of state and transitions. Verification asks what can
happen under **all enabled action choices** from the declared initial states.
Results depend on the completeness of that model: an omitted action, guard or
domain case can make the model prove a property the real system does not satisfy.

## Scenarios, flows and exploration

| Check | Starts from | Establishes |
| --- | --- | --- |
| `Scenario` | Its concrete `given` snapshot | One action accepts or correctly rejects this example |
| `Flow` | Its concrete `given` snapshot | This sequence of actions and checkpoints executes successfully |
| Canonical invariant verification | `Spec.initial`, or defaults | Each listed invariant holds throughout reachable states |
| Query | Its own initial source, otherwise the canonical roots | The reachability or safety property for those roots |

A passing scenario covers that example. A passing flow shows one executable
journey. Neither establishes that all other action orders are safe; that is what
the reachability engine examines.

Scenarios and flows have **partial** worlds: only supplied entity instances are
present, and omitted scoped slots are absent. Canonical exploration starts with
entities constructible from defaults and scoped slots present by default. Supply
required field values and explicit `Absent(ref)` snapshots through an initial
relation or a query's `given` when needed. A missing required default can prevent
canonical verification even though all scenarios pass.

**Since 0.0.4:** `Scope(..., initially_present=False)` opts into absent defaults
for canonical/query worlds. Explicit snapshots override the scope policy; each
query-owned initial source starts independently from those defaults. Scenario
and flow partial worlds keep the same behavior. See the
[identity and presence example](dsl.md#declared-keys-and-initial-presence).

## Initial states and domains

`Spec.initial=Initial(vary=[...], where=[...], given=[...])` declares a finite set
of canonical roots. `vary` enumerates field domains; `where` filters combinations;
`given` fixes other field values or supplies instances without defaults.

Domains can come from booleans, enums, lifecycle states, bounded integer fields
or `Field(values=[...])`. A `BoundField` in `vary` expands over its scope.
`max_candidates` limits candidate generation; exceeding it is an error, never a
truncated selection of roots.

**Since 0.0.4:** omit `vary` (or use `vary=[]`) for a fixed relation:
`Initial(given=[...])` builds one candidate from defaults plus those snapshots.
`where` still applies, so a false filter yields an error rather than a vacuous
PASS. `Initial()` selects the defaults-built world. This does not require
enumerating finite domains for fields that stay fixed. Versions before 0.0.4 require a non-empty `vary`. See the [fixed-root example](dsl.md#fixed-root-example).

A query can specify **one** of `given`, `given_any` or `initial`:

- `given=[...]` supplies or overrides instances in the defaults-built root.
- `given_any=[[...], [...]]` enumerates admissible roots explicitly.
- `initial=Initial(...)` generates them declaratively.

Without its own initial source, a query uses the canonical roots. Multi-root
queries must satisfy their requirement for **every** admissible root; for
`Reachable`, each root must have a path to a matching state. A trace records which
root it starts from. For a passing multi-root `Reachable`, the trace is one
representative witness; the verdict checks every root, including paths that
merge. A complete failure identifies an initial state with no path (a native
trace has that root and zero steps). Missing paths under a capped or excluded
transition relation remain INCONCLUSIVE. TLC checks projected roots separately;
its state count sums those runs, and its timeout applies to each export.

An initial state that violates an invariant, or whose invariant cannot be
assessed, is retained but not expanded. Root legality keeps the overall verdict
FAIL, including selected checks. If a complete `Reachable` failure refers only
to such roots, `query.invalid_root` explains that reachability was not assessed
from the invalid root. If a legal root also has no path, its ordinary missing-path
diagnostic takes precedence. Native traces retain the invalid root with zero
steps; TLC traces carry the explanation without inventing state snapshots.

**Unreleased (#65):** even if a retained invalid root already matches the goal,
`Reachable` does not use it as a positive witness. A complete check reports FAIL
with the same invalid-root explanation. Capped/excluded proofs still remain
INCONCLUSIVE and predicate evaluation errors remain errors. Projection may choose
a legal representative of an equivalent root projection; its witness is legal,
while the original root-legality failure still blocks the overall result.
`Unreachable` retains its existing forbidden-state contract.

**Unreleased (#66):** TLC fallback reuses projected full-model root legality.
Inert roots are assessed locally with the native predicate/error rules; only
legal roots launch TLC. Mixed-query state counts include locally assessed roots,
but only actual TLC runs produce backend notes. A later legal missing path still
takes precedence, and backend errors or transition defects remain visible.

Numeric annotations alone do not bound a domain. An increasing `int` counter
without an upper bound may generate infinitely many distinct states. Use finite
abstractions and explicit bounds that reflect the requirement. Ordinary hard
bounds reject an out-of-range transition with a finding; `saturate=True` clamps
values at the thresholds and therefore changes the model's meaning.

## Verdicts and completeness

The command's overall `verdict` has three values. Individual invariant and query
results can additionally report `NOT_CHECKED`.

| Result | Meaning | Overall consequence |
| --- | --- | --- |
| `PASS` | The check established its requirement for the model and roots | Can contribute to overall PASS |
| `FAIL` | A counterexample, evaluation defect or other failure was found | Overall FAIL |
| `INCONCLUSIVE` | The available exploration did not settle the property | Prevents overall PASS |
| `NOT_CHECKED` | The property could not be evaluated, for example because no canonical initial state could be built | Prevents overall PASS |

An existential witness can settle a reachability check before the graph closes;
universal safety or unreachability requires sufficient complete coverage. A
concrete defect can fail a capped run. A property applicable in zero states
cannot silently pass: vacuous queries fail, while an invariant never evaluated
is NOT_CHECKED on a complete exploration and INCONCLUSIVE on a capped one.

Automatic invariant verification and scenario checks are distinct. An invariant
whose direct entity/slot references are absent from a scenario is skipped there;
finite quantifiers instead range over the present members. Empty `ForAll` is
true; empty `Min`/`Max` is an evaluation error. Include the required data when
using scenarios to exercise a rule.

For `check`, JSON `passed` is true only for an effective PASS. `--strict` makes
warnings fail the run. Exit codes are documented in the [CLI reference](cli.md#exit-codes).

## Transition semantics

All execution paths use one transition kernel. Preconditions and terminal/presence
guards can reject an action before effects. Effects apply simultaneously: every
right-hand side reads the pre-state. The checker then checks postconditions and
state invariants. A state violating an invariant is retained as a counterexample
but is not expanded further.

An action cannot modify **any field** of an entity whose lifecycle is terminal,
or delete that terminal entity. Two effects writing the same field are a
structural error. Reading or modifying an absent scoped instance is rejected.

`Expect.FAIL` passes only for an intended pre-execution rejection. An effect
error, failed postcondition or failed `then` assertion is still a failed scenario.
Events are materialized observations; emission does not automatically dispatch
another action. Exploration excludes actions requiring external event payloads
and reports them as unassessed rather than falsely declaring them dead.

## Slices, budgets and repeated checks

By default, `check` explores each invariant or query on its **cone of influence**:
the state it reads, the actions that can affect it, and the dependencies of those
actions. Independent processes need not pay for their full Cartesian product.
JSON records the slice. `check --no-slice` uses the whole model instead.

`Spec.max_states` bounds canonical invariant exploration and supplies the default
budget for queries, including queries with their own roots. An explicit query
`max_states` overrides that default. `check --max-states N` overrides all budgets for that invocation.
An exhausted budget preserves INCONCLUSIVE. Raising the budget can help a large
finite model, but cannot close an unbounded domain.

`trace` follows the property exploration used by `check`; `trace --no-slice`
selects the whole-model path. `explore` always explores the whole model for its
chosen roots. Sliced traces keep out-of-slice fields at their root values. One
documented difference is that whole-model `NoDeadEnd` counts a state illegal under
an out-of-slice invariant as a dead end, while that slice does not; the invariant
violation still fails the run in its own check.

**Since 0.0.3:** `check --cache` persists explorations by a digest of the slice,
roots, budget and engine source. An unchanged slice can reuse work across runs;
model changes invalidate the relevant entries. The cache returns the same
semantic findings as a fresh run. Check timing can change because it measures
work actually performed, and shared work is charged to its first consumer.

### Projected safety proofs (Unreleased)

Sliced verification can first check an invariant or `Unreachable` on a
projection of its effective initial states. It follows every expanded writer
of a retained field and keeps inputs to visible updates, postconditions,
payloads and lifecycle checks. It erases hidden writes and can weaken a
precondition by removing a conjunct that reads an erased field. The projected
graph covers every reachable concrete state for the retained fields.

A complete, error-free result with a legal, applicable concrete root can
prove safety. The budgeted attempt leaves world-invariant pruning disabled.
A projected counterexample describes a candidate path. The checker tries that
path from the matching concrete roots with the original transition kernel and
world invariants. When the exact retry reaches its budget, a replayed violation
still establishes failure. The checker keeps exact action coverage for
transition diagnostics. Unsupported projections and unsuccessful proofs use
the existing exact verification pipeline.

## TLC fallback

`check --tlc` hands supported properties left INCONCLUSIVE to TLC on the same
slice. It requires Java and a TLC jar, selected by `ANALINT_TLC_JAR` or a discovered
Quint/Apalache installation. Use `--tlc-timeout SECONDS` to bound each exported
check. A result decided by TLC carries `backend: "tlc"`.
**0.1.0:** selected safety queries can first use an unconstrained proof
attempt, including TLC when requested. Only a clean PASS discharges support;
all other attempts return to constrained verification. Own-root attempts never
inherit canonical invariant trust. See [check selection](cli.md#selecting-checks-over-one-model).

The exporter mirrors the transition kernel and refuses constructs it cannot
represent. Unsupported exports and timeouts leave the property INCONCLUSIVE.
Current fallback supports invariants and `Reachable`, `Unreachable` and
`AlwaysHolds`; `NoDeadEnd` and `DeadActions` are not exported. Floats,
`Min`/`Max` and unsafe absent-slot reads are examples of export restrictions.
**0.1.0:** emitted payload constraints use the same post-state, nullable and
non-clamping rules as native verification. A transition defect found by TLC makes
the run FAIL; the target property's status can remain INCONCLUSIVE when TLC stops
before deciding it. Defect diagnostics show the reachable prefix and attempted
action. Custom event constructors and literal strings colliding with the reserved
`__null__` representation remain explicit export refusals.
TLC is an additional verifier for the same finite abstraction; it does not turn
an unbounded or incomplete model into a proven system.

## Recoverability and scope boundaries

`NoDeadEnd(goal=...)` asks whether a path to the goal exists from every reachable
state. A system can satisfy this while repeatedly choosing a loop and never
finishing. The query establishes **recoverability**, not liveness, fairness or
termination of every execution.

analint does not model scheduling fairness, real time, probabilities, unbounded
collections, automatic event delivery or concurrency inside one action. Model
finite state alternatives explicitly and keep these assumptions visible. It
also does not check that implementation code conforms to the model.
