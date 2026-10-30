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

**Unreleased:** `Scope(..., initially_present=False)` opts into absent defaults
for canonical/query worlds. Explicit snapshots override the scope policy; each
query-owned initial source starts independently from those defaults. Scenario
and flow partial worlds keep the same behavior. See the
[identity and presence example](dsl.md#declared-keys-and-initial-presence-unreleased).

## Initial states and domains

`Spec.initial=Initial(vary=[...], where=[...], given=[...])` declares a finite set
of canonical roots. `vary` enumerates field domains; `where` filters combinations;
`given` fixes other field values or supplies instances without defaults.

Domains can come from booleans, enums, lifecycle states, bounded integer fields
or `Field(values=[...])`. A `BoundField` in `vary` expands over its scope.
`max_candidates` limits candidate generation; exceeding it is an error, never a
truncated selection of roots.

**Unreleased:** omit `vary` (or use `vary=[]`) for a fixed relation:
`Initial(given=[...])` builds one candidate from defaults plus those snapshots.
`where` still applies, so a false filter yields an error rather than a vacuous
PASS. `Initial()` selects the defaults-built world. This does not require
enumerating finite domains for fields that stay fixed. In 0.0.3, `vary` must
still be non-empty. See the [fixed-root example](dsl.md#fixed-root-example-unreleased).

A query can specify **one** of `given`, `given_any` or `initial`:

- `given=[...]` supplies or overrides instances in the defaults-built root.
- `given_any=[[...], [...]]` enumerates admissible roots explicitly.
- `initial=Initial(...)` generates them declaratively.

Without its own initial source, a query uses the canonical roots. Multi-root
queries must satisfy their requirement for **every** admissible root; for
`Reachable`, each root must have a path to a matching state. A trace records which
root it starts from.

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

`Spec.max_states` bounds canonical invariant exploration; queries have their own
`max_states`. `check --max-states N` overrides all budgets for that invocation.
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

## TLC fallback

`check --tlc` hands supported properties left INCONCLUSIVE to TLC on the same
slice. It requires Java and a TLC jar, selected by `ANALINT_TLC_JAR` or a discovered
Quint/Apalache installation. Use `--tlc-timeout SECONDS` to bound each exported
check. A result decided by TLC carries `backend: "tlc"`.

The exporter mirrors the transition kernel and refuses constructs it cannot
represent. Unsupported exports and timeouts leave the property INCONCLUSIVE.
Current fallback supports invariants and `Reachable`, `Unreachable` and
`AlwaysHolds`; `NoDeadEnd` and `DeadActions` are not exported. Floats,
`Min`/`Max` and unsafe absent-slot reads are examples of export restrictions.
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
