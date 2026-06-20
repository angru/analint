# DSL contract stabilization review

**Date:** 2026-06-20

**Purpose:** decide whether analint's authoring and machine-facing contracts are
stable enough to document and publish, and identify any large change that is
cheaper to make before the first public release.

This review is deliberately stricter than a feature review. The question is not
"can the current API express the examples?" It can. The question is whether the
current concepts say exactly what they mean, whether repeated authoring cost is
buying semantics, and whether the public names are the ones we want to teach for
years.

`ROADMAP.md` remains the source of truth for implementation status. This file is
the decision rationale for roadmap block C.

---

## 1. Executive verdict

The **semantic kernel is settled**:

```text
typed finite state
+ invariants
+ guarded simultaneous transitions
+ concrete examples and executable traces
+ bounded reachability properties
```

Do not replace it with a logic-programming language, controlled English, YAML,
decorated Python functions, or a new textual grammar. Those alternatives either
lose transition semantics, reintroduce opaque execution, or add a parser and a
second language without removing the domain complexity.

The **public contract is not fully frozen yet**. It needs one bounded pre-doc
cleanup, not another language redesign:

1. remove semantic-looking metadata that does not affect behaviour
   (`Actor`/`by`, `on`, `requires`, documentary-only `Flow`);
2. decide and narrow the surprising entity-wide meaning of lifecycle
   `terminal`;
3. make common predicates and checkpoints use the expressions authors already
   wrote, without `== True` and `Assert(...)`;
4. make lifecycle transition tables use a native mapping instead of repeated
   `Transition(...)` wrappers;
5. fix the two advanced-surface costs repeated by independent external models:
   scope identity as a value and explicit initial presence;
6. version every JSON/MCP wire shape, not only the exploration artifact.

After those decisions and migrations, the API is stable enough for the MkDocs
site. The expected result is a smaller *mental* surface and a modest source-size
reduction. Claims of a dramatic line-count reduction would be dishonest: most
lines in serious examples describe real states, actions, examples, and
properties.

---

## 2. Evidence from the repository

### 2.1. Surface inventory

The current top-level `analint.__all__` exports **48 symbols**.

Representative authored declarations across `examples/`:

| Construct | Count |
|---|---:|
| `Action(...)` | 91 |
| `Scenario(...)` | 113 |
| `Assert(...)` | 125 |
| `Set(...)` | 109 |
| `Transition(...)` | 26 |
| `Param(...)` | 25 |
| `Reachable(...)` | 16 |
| `Unreachable(...)` | 14 |
| `Lifecycle(...)` | 14 |
| `Flow(...)` | 8 |
| `Scope(...)` | 5 |

The 48 exports overstate the beginner surface: quantifiers, presence, bounded
multiplicity, composition, and query variants are advanced features. But they
also make "eight primitives" an obsolete description of the authoring API.
Documentation should present progressive layers rather than pretend every
export is equally fundamental.

### 2.2. Where the volume actually comes from

Ranked by authoring cost:

1. **Examples and fixtures.** There are 113 scenarios, 123 `given=` clauses and
   125 assertion wrappers. This is useful executable evidence, but repeated
   snapshots dominate many files.
2. **Real domain detail.** External models need explicit states, guards,
   effects, and properties. Branch protection is 455 lines because the policy
   has many independently tested conditions, not because `Action` is badly
   shaped.
3. **Advanced identity plumbing.** OAuth and Kubernetes independently need a
   static relation that maps a `Scope` slot to a second value-level identifier.
   This is repeated accidental complexity.
4. **Wrapper syntax.** `Assert(predicate)`, `Transition(source, targets)`, and
   `bool_field == True/False` add syntax without adding meaning.
5. **Semantic-looking metadata.** Twelve `by=`, seven `on=` and five
   `requires=` declarations invite behavioural interpretations the engine does
   not implement.

The core action form is not the main problem:

```python
Action(
    pre=[...],
    effect=[Set(...), ...],
)
```

It already has high semantic density. Replacing it would mostly move the same
information into a less inspectable notation.

### 2.3. Irreducible volume

The following cannot be removed without weakening the model:

- finite domains and exploration bounds;
- distinct guards for distinct permitted transitions;
- simultaneous next-state facts;
- concrete initial snapshots where defaults are insufficient;
- properties that state what must be reachable or impossible;
- examples that isolate independent policy conditions.

A shorter model is not automatically a better model. If one compressed row
silently represents ten materially different cases, reviewability got worse.

---

## 3. What analint is — and is not

### 3.1. The useful combination

No single external concept defines analint. Its core is a practical combination:

| Source tradition | What analint should keep |
|---|---|
| DDD | domain-shaped names: entities, invariants, events, ubiquitous language |
| State machines/statecharts | explicit lifecycle states and allowed transitions |
| Planning / STRIPS | action guards and simultaneous state updates |
| Hoare-style contracts | `pre` / `effect` / `post` separation |
| Relational/model-checking languages | finite quantification, initial relation, exhaustive bounded search |
| BDD/Gherkin | examples as executable documentation |
| Policy/decision languages | named, reviewable rules and fail-closed evaluation |

This combination is the product. Selecting one tradition as the foundation
would make the others harder to express.

### 3.2. DDD is vocabulary, not semantics

DDD gives useful domain words, but it does not define bounded exploration,
simultaneous effects, reachability, or transition traces.

`Entity` is also broader here than a strict DDD entity: an unscoped analint
entity is one typed state record per class and may represent a game, namespace,
wallet, message, or policy aggregate. Keep the name because it is readable and
established, but document the analint meaning precisely instead of claiming a
perfect tactical-DDD correspondence.

`Actor` is the counterexample. A marker role with no identity or state is not a
semantic principal. Authorization requires a concrete principal and predicates
over its relation to the resource. Cedar's request model makes this distinction
explicit through `principal`, `action`, and `resource`; its annotations are also
explicitly non-evaluated metadata:

- https://docs.cedarpolicy.com/policies/syntax-policy.html

The existing `Actor`/`by` pair should therefore not stay in the semantic core.

### 3.3. Logic programming is useful internally, not as the user model

analint already uses logic-language ideas:

- predicates are values rather than callbacks;
- `ForAll` / `Exists` / aggregates range over finite scopes;
- `Initial(..., where=...)` is a finite relation;
- queries ask for witnesses or counterexamples.

But a Datalog/Prolog-style surface would be a regression for the target audience:

- transition order and next-state facts become less direct;
- mutable domain state has to be encoded through time/state indices;
- unification and rule firing introduce a second mental model;
- common business transitions stop reading as actions.

Keep the relational AST and fail-closed evaluator. Do not expose unification,
Horn clauses, or a general rule engine unless a future requirement cannot be
expressed as state + transition + property.

### 3.4. Controlled natural language should be output, not source

Gherkin succeeds as executable documentation because it structures examples
around Given/When/Then, but the free-form step text is resolved by separate step
definitions. The official reference explicitly separates the readable sentence
from the code that gives it meaning:

- https://cucumber.io/docs/gherkin/reference/

analint should borrow the example structure, not the indirection. Its current
`Scenario(given=..., action=..., then=...)` is machine-checkable without regex
step matching or hidden glue code.

Generated prose is valuable:

```text
Given a pending order with balance 10
When checkout is attempted
Then the action is blocked by "balance covers total"
```

That should be a renderer over the model, not the canonical authoring format.
LLMs may draft Python DSL, but natural-language interpretation must not become
part of verified semantics.

### 3.5. Decision tables are a future projection

DMN's stated goal is a notation understandable by analysts, developers, and
business users. Decision tables are strong for dense, mostly stateless
input-to-outcome rules:

- https://www.omg.org/spec/DMN/1.5/About-DMN

They are not a replacement for analint actions or reachability. A table can be a
useful alternate view for:

- many single-fault scenarios of one action;
- permission matrices;
- enum-state transition matrices;
- validation rules with identical output shape.

Add table import/export only after a real model demonstrates that the table is
clearer than named predicates plus scenarios. Do not add a second canonical
authoring format before publication.

### 3.6. More formal syntax is not the target

Quint deliberately separates stateless, state, action, run, and temporal modes
and exposes a broader mathematical vocabulary. It is the right reference for
formal expressiveness, not a syntax target for analint:

- https://quint.sh/docs/lang

analint should retain a smaller bounded domain/workflow niche. Adding primes,
temporal operators, set comprehensions, or symbolic nondeterminism would make it
more powerful and less suitable for the stated audience. Those are not free
improvements.

---

## 4. Stable conceptual contract

The following concepts should be documented as stable after the cleanup.

### 4.1. State

- `Entity` declares a typed domain state record.
- `Field` declares a scalar domain/default and exploration bounds.
- `Scope` declares a fixed finite universe of identified entity slots.
- class/ref/param/bound field access creates symbolic expressions.

Do not rename `Entity` to `State`, `Record`, or `Model`. Each alternative is
either less domain-shaped or conflicts with lifecycle state terminology.

### 4.2. Rules and properties

- plain predicate expressions are reusable facts;
- `Invariant` is a model constraint, checked on scenario/flow states and
  automatically over the canonical reachable graph;
- `Reachable`, `Unreachable`, `AlwaysHolds`, `NoDeadEnd`, and `DeadActions`
  are explicit exploration questions.

`Invariant` and `AlwaysHolds` are not duplicates. The latter can have a
query-specific source and budget; the former is part of the canonical model.

### 4.3. Transitions

- `Action.pre` decides enabledness;
- `Action.effect` is a set of simultaneous next-state facts;
- `Action.post` checks the accepted result;
- all right-hand sides read the pre-state;
- conflicting writes are structural errors.

Keep `Set` as the canonical effect. Keep `Add` and `Subtract` as readable sugar;
they are common enough and do not add a new semantic category.

Do not introduce function-bodied actions:

```python
@action
def checkout(world):
    world.balance -= world.total
```

That form is shorter only because it hides simultaneity, turns the host language
into verified semantics, and prevents complete structural inspection.

### 4.4. Examples and traces

- `Scenario` is one concrete action attempt from one concrete world;
- `Flow` is an executable multi-action trace with checkpoints;
- `Expect.FAIL` means pre-execution rejection, not "any internal failure."

Keep `Scenario` rather than rename it to `Example`: the established name is
clear, and the `Expect.FAIL` distinction is stronger than a generic example.

### 4.5. Initial relation and composition

- `Initial` describes a finite set/relation of canonical roots;
- `Contract` exports an explicit reusable fragment;
- `Spec` is the single root and configuration boundary.

Explicit `Contract` lists are intentional ceremony. They are the public export
boundary; auto-discovering a contract from module imports would reintroduce the
composition leak it was designed to prevent.

---

## 5. Changes recommended before documentation

### 5.1. Remove semantic-looking metadata from the core

#### Remove `Actor` and `Action.by`

`Actor` is a marker class and `by` does not affect enabledness. It therefore
cannot express authorization or identity-sensitive behaviour.

Canonical replacement:

```python
principal = Param("principal", users)

cancel = Action(
    params=[principal],
    pre=[
        principal.active,
        In(principal.role, [Role.CUSTOMER, Role.ADMIN]),
        order.customer_id == Key(principal),
    ],
    effect=[Set(order.status, Status.CANCELLED)],
)
```

If the actor is only prose, put it in `name`, `description`, or `tags`. Do not
keep a dedicated core class for metadata.

#### Remove `Action.on`

`on` does not gate exploration or consume an event. State predicates already
carry the operational causality in current models. Keep `Event` and `emits`,
which are materialized by the kernel and can be checked by scenarios/flows.
Reintroduce event input only with a real event-pool/dispatch semantics.

#### Remove `Action.requires`

Executable `Flow` is the honest way to state and verify ordering. A documentary
edge that the explorer deliberately ignores is not a transition constraint.

#### Make `Flow` always executable

`given=None` currently changes `Flow` from executable behaviour to
documentation. That hidden mode is unnecessary. Require an initial world
(`given=[]` is valid when defaults are sufficient). A non-executable journey
belongs in prose or a diagram.

This removes four places where readers must remember "looks semantic, but is
metadata."

### 5.2. Narrow lifecycle `terminal`

Current behaviour freezes **every field of an entity** when any lifecycle field
is terminal. That is stronger than ordinary state-machine semantics and is
surprising for entities with audit fields, notes, counters, or multiple
lifecycle fields.

Recommended meaning:

- a terminal value has no outgoing transition for that lifecycle field;
- changing that lifecycle field out of the terminal value is rejected;
- unrelated fields are not implicitly immutable;
- deletion is governed by presence/action rules, not by an unrelated lifecycle
  field.

Do not add a `freeze_entity=True` option until a real model needs it. Whole-entity
immutability can be expressed by explicit action guards and is not currently
evidence-backed.

This is the only recommended change that materially narrows runtime semantics.
It must be decided before docs because "terminal" is otherwise easy to teach
incorrectly.

### 5.3. Accept boolean fields directly in predicate positions

Current:

```python
mergeable = And(
    PullRequest.code_owner_approved == True,
    PullRequest.changes_requested == False,
)
```

Recommended:

```python
mergeable = And(
    PullRequest.code_owner_approved,
    Not(PullRequest.changes_requested),
)
```

Predicate-bearing constructors and `pre`/`post`/query fields should normalize a
boolean field reference to `field == True`. `Not` normalizes before negation.
Non-boolean fields in a predicate slot remain a structural/type error.

Benefits:

- removes the `E712` lint exception from specs;
- reads naturally;
- static checkers already see a class annotation of `bool`, so this is friendlier
  to the accepted dual-view typing boundary;
- adds no new public symbol.

Do not overload Python `and`, `or`, or `not`; Python does not provide an AST-safe
operator hook for them. Keep `And`/`Or`/`Not`.

### 5.4. Accept raw predicates as checkpoints; retire `Assert`

Current:

```python
then=[Assert(Order.status == Status.PAID)]

steps=[
    checkout,
    Assert(Order.status == Status.PAID),
]
```

Recommended:

```python
then=[Order.status == Status.PAID]

steps=[
    checkout,
    Order.status == Status.PAID,
]
```

The container already establishes the meaning: entries in `Scenario.then` and
predicate entries in `Flow.steps` are assertions. `Assert` repeats placement
semantics and is the most common removable wrapper in the repository (125
uses).

Keep `Emitted(EventType)` because an event class alone is ambiguous and is not a
predicate. Deprecate `Assert` for one pre-1.0 migration cycle, then remove it
from the top-level exports.

### 5.5. Use a mapping for lifecycle transitions; retire `Transition`

Current:

```python
status: Status = Lifecycle(
    initial=Status.PENDING,
    transitions=[
        Transition(Status.PENDING, [Status.PAID, Status.CANCELLED]),
        Transition(Status.PAID, [Status.CANCELLED]),
    ],
    terminal=[Status.CANCELLED],
)
```

Recommended:

```python
status: Status = Lifecycle(
    initial=Status.PENDING,
    transitions={
        Status.PENDING: [Status.PAID, Status.CANCELLED],
        Status.PAID: [Status.CANCELLED],
    },
    terminal=[Status.CANCELLED],
)
```

A native mapping exactly represents the relation, makes duplicate source states
impossible by construction, and removes one public wrapper type. Internally the
mapping may normalize to the existing transition records.

Do not infer terminal states from missing mapping keys. "No declared outgoing
edge" and "terminal business state" are not always the same claim.

### 5.6. Make scope identity usable as a value

OAuth and Kubernetes independently reproduce the same workaround:

```python
_slot_is_its_id = [
    Implies(code == codes["c1"], code_id == CodeId.C1),
    Implies(code == codes["c2"], code_id == CodeId.C2),
]
```

This is evidence for one missing authoring abstraction. Add a small expression
such as `Key(ref_or_param_or_bound)` that resolves to the `Scope` key.

Then use domain identifiers as keys:

```python
replicasets = Scope(ReplicaSet, keys=[Owner.RS0, Owner.RS1], initially_present=True)
pods = Scope(Pod, keys=["p0", "p1", "p2"], initially_present=False)

rs = Param("rs", replicasets)
slot = Param("slot", pods)

reconcile_create = Action(
    params=[rs, slot],
    pre=[owned(Key(rs)) < rs.desired, live_pods < Namespace.quota],
    effect=[Create(slot, owner=Key(rs))],
)
```

This removes the parallel `rs_owner` / `code_id` parameters and their static
`where` maps without adding general joins or dynamic identity.

`Key` should be a closed AST/value-expression node. Do not expose
`InstanceRef` as the domain value itself; that would leak engine identity into
user schemas and JSON.

### 5.7. Make initial scope presence explicit

The canonical explorer currently defaults scoped slots to present, while
scenarios omit unlisted slots as absent. Kubernetes had to vary an unrelated
field only because `Initial` disallows an empty `vary`.

Require an explicit canonical presence policy on `Scope`:

```python
accounts = Scope(Account, keys=[...], initially_present=True)
pods = Scope(Pod, keys=[...], initially_present=False)
```

Also allow fixed initial relations:

```python
Initial(given=[...])  # vary defaults to []
```

This removes an arbitrary restriction and makes the canonical world readable at
the scope declaration. Explicitness is preferable to choosing one global
default: accounts, players, and code slots often start present; resource slots
often start absent.

### 5.8. Keep parameter declaration explicit for now

It is technically possible to infer `Action.params` by walking `where`, `pre`,
`effect`, and `emits`. Do not do it in this cleanup.

The explicit list:

- states the action signature in one place;
- gives deterministic binding order;
- catches accidentally captured params;
- costs one line only on advanced actions.

Inference would replace visible ceremony with loader magic. Revisit only if
larger models repeatedly show the list drifting from actual usage.

---

## 6. Public surface after the cleanup

Documentation should present layers, not one flat list.

### Core authoring

```text
Entity, Field
Invariant
Action, Set, Add, Subtract
Scenario, Expect, Emitted
Flow
Spec
```

### Verification

```text
Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions
```

### Advanced finite modeling

```text
Scope, Param, Bound, Initial
ForAll, Exists, Count, Sum, Min, Max, Present, Absent, Create, Delete, Key
Contract
```

### Predicate vocabulary

```text
And, Or, Not, Implies, In, IsNull, IsNotNull
```

`Predicate`, `Effect`, and `InstanceRef` are typing/internal boundary types, not
normal constructors. They should not be taught in the main DSL reference.
Whether they remain top-level imports for typing compatibility is less important
than keeping them out of the beginner surface.

The target is not the smallest possible `__all__`. The target is that every
normal authoring symbol either changes model semantics or denotes a necessary
check.

---

## 7. Rejected syntax directions

### 7.1. A new standalone language

Rejected before evidence of non-Python demand.

Costs:

- parser, formatter, syntax highlighting, language server and packaging;
- duplicated type/module system;
- migration and interoperability work;
- a second canonical representation before there is an IR consumer.

Python currently supplies modules, enums, names, comments, editors, packaging,
and agent familiarity. The metaclass/type-checker boundary is real but smaller
than building a language.

### 7.2. YAML/JSON authoring

Rejected as canonical source.

It is more verbose for expressions, weaker for reuse and names, and pushes every
predicate into strings or a bespoke nested data format. JSON is appropriate for
machine output, not the human authoring surface.

### 7.3. Fluent builders and chained methods

Examples such as:

```python
action("checkout").when(...).set(...).emit(...)
```

save punctuation but hide plain values behind mutation/order, worsen diffs, and
make auto-discovery/type boundaries harder. Keyword constructors are boring and
reviewable. Keep them.

### 7.4. Decorators and function bodies

Rejected because they imply execution order and Python control flow. analint's
effects are simultaneous facts, not statements.

### 7.5. Domain profiles full of aliases

`Scene = Action`, `Character = Actor`, or `Operation = Action` creates vocabulary
forks without semantic gain. It makes search, documentation, and agent prompts
less uniform. Domain guides may explain how core concepts map to games or
workflows; the code should retain one vocabulary.

### 7.6. More temporal/formal operators

Rejected until a real target requirement cannot be honestly framed as bounded
safety/reachability. Quint, TLA+, FizzBee, and P are stronger choices for
fairness, unbounded temporal reasoning, and message interleavings.

---

## 8. Machine-facing contract review

The CLI/MCP surface is part of the product, not incidental tooling.

### Stable

- command/tool names: `check`, `show`, `affects`, `explore`, `trace`;
- exit codes 0/1/2/3/4;
- compact exploration by default;
- explicit completeness and `INCONCLUSIVE`;
- `analint.exploration/v1` artifact;
- graph size guard in MCP.

### Fix before docs

1. Add a `schema` identifier to every machine-facing JSON result:
   check, show, affects, trace, and structured errors. Exploration already does
   this correctly.
2. Align CLI and MCP `show` behaviour when `kind` is supplied without `name`.
3. Make `--format` an enum/Literal so invalid values are usage errors rather
   than silently selecting terminal output.
4. Update stale descriptions that still say check runs only structural checks
   and scenarios, or that MCP exposes only three tools.
5. State which JSON fields are stable and which are presentation-only. Python
   reporter dataclasses should remain internal.

The JSON schema version is more important to agents than preserving every
Python helper class. Freeze it deliberately.

---

## 9. API freeze matrix

| Area | Verdict | Before docs |
|---|---|---|
| `Entity` + annotation-first fields | stable | document dual class/instance view |
| `Field` domains/defaults/bounds | stable | no change |
| predicates and arithmetic AST | stable | add bool-field normalization |
| `Invariant` | stable | clarify canonical auto-check |
| `Action(pre/effect/post/emits)` | stable | remove `by/on/requires` |
| simultaneous effects | frozen semantic guarantee | no change |
| `Set/Add/Subtract/Create/Delete` | stable | no change |
| `Lifecycle` concept | stable | mapping syntax; narrow terminal semantics |
| `Transition` wrapper | unnecessary public type | deprecate/remove |
| `Scenario` + `Expect` | stable | raw predicate checkpoints |
| `Assert` wrapper | unnecessary | deprecate/remove |
| `Flow` concept | stable | executable only |
| `Event` output + `emits` | stable within stated boundary | document no dispatch |
| `Actor` / `by` | misleading metadata | remove |
| `on` / `requires` | misleading metadata | remove |
| `Scope` / `Param` / `Bound` | stable advanced concepts | add `Key`; explicit initial presence |
| `Initial` | stable concept | allow fixed relation with empty `vary` |
| quantifiers/aggregates/presence | stable advanced concepts | no expansion |
| `Contract` / `Spec` | stable | no change |
| query set | stable | no new temporal queries |
| CLI command names/exit codes | stable | tighten format validation/docs |
| MCP tool names | stable | align semantics/docs |
| exploration artifact | frozen at v1 | no change |
| other JSON results | not yet versioned | add schemas before docs |

---

## 10. Ranked ponytail audit

- `delete:` `Actor` and `Action.by`; model a principal as scoped state/`Param`,
  or keep prose in metadata. [`src/analint/models/actor.py`,
  `src/analint/models/action.py`]
- `delete:` documentary `Action.on` and `Action.requires`; executable state
  guards and `Flow` already carry causality/order. [`src/analint/models/action.py`]
- `delete:` non-executable `Flow` mode; require `given` and run every flow.
  [`src/analint/models/flow.py`]
- `shrink:` accept predicates directly in `Scenario.then` and `Flow.steps`;
  remove 125 `Assert(...)` wrappers. [`src/analint/models/scenario.py`,
  `src/analint/models/flow.py`]
- `shrink:` normalize boolean field refs in predicate positions; remove
  `== True/False` and spec-wide E712 exceptions. [`src/analint/models/predicate.py`,
  `src/analint/models/action.py`]
- `native:` use a dict for lifecycle edges; remove 26 `Transition(...)`
  wrappers from examples. [`src/analint/models/lifecycle.py`]
- `shrink:` add a closed `Key(...)` expression; delete duplicated identity
  params and implication maps in OAuth/Kubernetes. [`src/analint/models/scope.py`]
- `shrink:` explicit scope initial presence + `Initial(given=...)`; delete the
  artificial Kubernetes varying field workaround. [`src/analint/models/initial.py`]

Estimated repository effect: roughly **60–100 authored lines**, **3–5 top-level
concepts**, and no dependency reduction. The larger gain is removing four false
semantic affordances and two repeated modeling workarounds.

---

## 11. Recommended implementation sequence

Keep the migration small and reviewable:

1. Lock semantic decisions: terminal meaning; removal of `Actor/by/on/requires`;
   executable-only `Flow`.
2. Add characterization tests for the new canonical forms before migrating
   examples.
3. Implement bool predicate normalization and raw checkpoints.
4. Add lifecycle mapping input while temporarily accepting `Transition`.
5. Add `Key` and explicit scope initial presence; migrate OAuth and Kubernetes
   first because they are the evidence cases.
6. Migrate remaining examples and remove deprecated exports.
7. Version check/show/affects/trace JSON and align CLI/MCP behaviour.
8. Run the full suite and characterization snapshot; only then mark roadmap
   block C complete and begin MkDocs.

Do not combine this with new verification semantics, visualization, an IR, or a
docs-site build. The purpose is to freeze the contract, not reopen the roadmap.

---

## 12. Final publication decision

**Do not publish the full documentation against the current surface.**

**Do not redesign the DSL.**

Make the bounded cleanup in §5 and §8, then freeze:

- state/action/invariant/query semantics;
- the layered vocabulary;
- machine-facing JSON schemas;
- the explicit boundary: bounded reachability, no liveness/fairness/event
  dispatch.

After that, the remaining verbosity is mostly the honest cost of specifying a
system precisely. Further compression should be evidence-driven and preferably
implemented as views, renderers, fixtures, or narrow sugar—not new semantic
primitives.
