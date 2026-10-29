# DSL reference

Import public declarations from `analint`. The
[first-spec tutorial](getting-started.md) is a complete runnable model; snippets
below illustrate individual declarations and may refer to names defined there
or in the linked examples.

## State: Entity and Field

Subclass `Entity` and annotate fields. An instance carries values; a class-level
field is an expression used in predicates and effects.

```python
from analint import Entity, Field


class Wallet(Entity):
    balance: int = Field(0, ge=0, le=5)


Wallet(balance=3)       # concrete snapshot
Wallet.balance >= 1    # predicate, evaluated against a state later
```

Fields without defaults are required in snapshots. Unknown, missing required or
constraint-violating values are rejected at construction.

| Field option | Meaning |
| --- | --- |
| `Field(default, ge=..., gt=..., le=..., lt=...)` | Numeric constraints, checked on snapshots and transitions |
| `Field(default, values=[...])` | Explicit finite scalar domain |
| `Field(default, ge=..., le=..., saturate=True)` | Clamp numeric effects at thresholds instead of rejecting an overflow |
| `Lifecycle(...)` as a field default | Initial value, allowed edges and terminal states for a state field |

Booleans, enums, lifecycle states, bounded integers and explicit value domains
can supply finite choices to `Initial`. Numeric bounds define the abstraction:
use thresholds deliberately, especially with saturation.

## Predicates and expressions

Comparisons `==`, `!=`, `<`, `<=`, `>` and `>=` build predicate values. Fields and
arithmetic expressions support `+`, `-` and `*`. Name expressions and predicates
to reuse them; they are data, not callbacks.

```python
from analint import And, Implies, In, IsNotNull, IsNull, Not, Or

can_pay = And(Wallet.balance >= Order.total, Order.total > 0)
remaining = Wallet.balance - Order.total
```

Use `And(...)`, `Or(...)`, `Not(...)` and `Implies(a, b)`, rather than Python
`and`, `or`, `not` or chained comparisons. `In(field, values)`, `IsNull(field)`
and `IsNotNull(field)` cover membership and null checks. Boolean fields can
appear directly in predicate positions, such as `pre=[Client.active]`.

## Invariant

`Invariant(predicate, id="", label="")` describes a state relationship.

```python
from analint import Implies, Invariant

resolved_leaves_no_open_ticket = Invariant(
    Implies(Ticket.status != Status.NEW, Queue.open_tickets == 0),
    label="Resolving the only ticket clears the queue counter",
)
```

Listed invariants are automatically verified from the canonical roots and
checked before and after scenario/flow actions where applicable. Direct reads
of a missing instance make an invariant inapplicable to that snapshot. Quantified
reads follow present scope members. Keep one-field constraints in `Field`;
use invariants for relationships between fields or entities.

## Action and effects

`Action(pre=[...], effect=[...], post=[...], emits=[...])` declares a transition.
Metadata includes `id`, `name`, `description` and `tags`.

```python
from analint import Action, Set, Subtract

pay = Action(
    pre=[Wallet.balance >= Order.total],
    effect=[
        Subtract(Wallet.balance, Order.total),
        Set(Order.paid, True),
    ],
    post=[Order.paid],
)
```

| Effect | Meaning |
| --- | --- |
| `Set(field, value_or_expression)` | The field has this value in the next state |
| `Add(field, amount)` / `Subtract(field, amount)` | Arithmetic forms of `Set` |
| `Create(ref, **fields)` | An absent scoped slot becomes present; omitted fields take defaults |
| `Delete(ref)` | A present scoped slot becomes absent |

Effects are **simultaneous**: every right-hand side reads the pre-state, so list
order cannot express a sequence. Two writes to one field are invalid. A slot
cannot be created/deleted and also written by another effect in the same action.
Use multiple actions in a flow when intermediate states matter.

## Lifecycle

Declare a lifecycle inline as a field default:

```python
from analint import Lifecycle

status: Status = Lifecycle(
    initial=Status.NEW,
    transitions={
        Status.NEW: [Status.RESOLVED],
        Status.RESOLVED: [Status.ARCHIVED],
    },
    terminal=[Status.ARCHIVED],
)
```

Effects that change the field must follow a declared edge. `terminal` freezes
the **whole entity**, including its other fields and deletion. Missing outgoing
edges do not implicitly declare a terminal state. A declared edge out of a
terminal state is a structural error.

## Scope, presence and instance references

A `Scope(EntityClass, keys=[...])` allocates a fixed finite universe. Indexing
returns an `InstanceRef`; `ref.field` addresses a particular instance and
`ref(field=value)` creates its snapshot.

```python
from analint import Absent, Present, Scope

wallets = Scope(Wallet, keys=["alice", "bob"])
alice = wallets["alice"]
bob = wallets["bob"]

alice_has_funds = alice.balance > 0
alice_exists = Present(alice)
# Snapshot entries: alice(balance=3), Absent(bob)
```

Use instance fields rather than ambiguous `Wallet.balance` once Wallet is scoped.
Only one scope per entity type is supported. `Absent(ref)` marks a slot absent;
`Present(ref_or_bound_or_param)` tests membership. Scenarios/flows omit slots as
absent, while exploration defaults them to present unless overridden.

Ordinary field reads and writes need a present slot. `Create` requires absence,
`Delete` requires presence; a mismatch rejects the action before effects. Keys
never grow dynamically. Explicit canonical scope-presence configuration and a
`Key(...)` value expression are deferred; they are not current API.

## Param: finite action families

`Param(name, *domain)` accepts explicit values, entity classes, enums, booleans
or a scope. `Param(name, ge=N, le=M)` declares an inclusive integer range.

```python
from analint import Action, Add, Param, Subtract

src = Param("src", wallets)
dst = Param("dst", wallets)

transfer = Action(
    params=[src, dst],
    where=[src != dst],
    pre=[src.balance >= 1, dst.balance < 5],
    effect=[Subtract(src.balance, 1), Add(dst.balance, 1)],
)

alice_pays_bob = transfer.bind(src=alice, dst=bob)
```

The declaration expands into ordinary bound actions when the Spec is built.
`where` filters static parameter combinations; state-dependent conditions,
including `Present`, belong in `pre`. List the family on `Spec.actions`, and use
`.bind(...)` to select the concrete action for a scenario or flow. Do not generate
model elements with Python factory loops; finite families belong in `Param`.

## Bound, quantifiers and aggregates

`Bound(name, scope)` binds a variable over present instances of that scope.

```python
from analint import Bound, Count, Exists, ForAll, Max, Min, Sum

wallet = Bound("wallet", wallets)
all_nonnegative = ForAll(wallet, wallet.balance >= 0)
someone_has_funds = Exists(wallet, wallet.balance > 0)
funded_count = Count(wallet, wallet.balance > 0)
total_balance = Sum(wallet, wallet.balance)
```

`ForAll` and `Exists` are predicates. `Count`, `Sum`, `Min` and `Max` are arithmetic
expressions usable in comparisons or effect right-hand sides. A bound field must
occur within its quantifier/aggregate, or in the supported `Initial.vary` position.

| Empty present set | Result |
| --- | --- |
| `ForAll` | `True` |
| `Exists` | `False` |
| `Count`, `Sum` | `0` |
| `Min`, `Max` | Evaluation error |

## Initial

`Initial(vary=[...], where=[...], given=[...], max_candidates=10000)` enumerates
admissible roots. `given` fixes values, and `where` filters combinations with
ordinary predicates and aggregates.

**Unreleased:** `vary` can be omitted or empty. `Initial(given=[...])` starts
with one candidate built from defaults plus the supplied snapshots, then applies
`where`. `Initial()` uses the defaults alone. A rejected candidate leaves no roots
and fails validation; an evaluation error also fails. Version 0.0.3 still requires
at least one varying field.

```python
from analint import Initial

starting_balances = Initial(
    vary=[alice.balance],
    where=[alice.balance >= 1],
    given=[bob(balance=0)],
)
```

Attach it to `Spec.initial` for canonical verification or to a query's `initial`
for that query only. Candidate overflow and evaluation errors fail rather than
silently removing combinations. See [initial states](concepts.md#initial-states-and-domains).

### Fixed-root example (unreleased)

Save this complete source as `spec.py` in a source-checkout environment and run
`analint check .`. Both slots start absent; creating one increments the counter.
The required Limit value comes from `given`. An independent noise action shows
why property slices can be smaller than `analint explore .`'s whole-model graph.
`already_created` supplies its own fixed root and needs no action to find a witness.

```python title="fixed-root-spec.py"
from analint import (
    Absent, Action, Add, Bound, Create, Entity, Field, Initial,
    Invariant, Not, Present, Reachable, Scenario, Scope, Set, Spec, Sum,
)


class Limit(Entity):
    max_created: int


class Counter(Entity):
    n: int = Field(0, ge=0, le=1)


class Item(Entity):
    units: int = Field(1, ge=1, le=1)


class Noise(Entity):
    on: bool = False


items = Scope(Item, keys=["one", "spare"])
one = items["one"]
spare = items["spare"]
item = Bound("item", items)

create = Action(
    pre=[Counter.n < Limit.max_created],
    effect=[Create(one), Add(Counter.n, 1)],
)
flip_noise = Action(pre=[Not(Noise.on)], effect=[Set(Noise.on, True)])
balanced = Invariant(Sum(item, item.units) == Counter.n)
created = Reachable(Present(one))
already_created = Reachable(
    Present(one),
    initial=Initial(given=[Limit(max_created=1), Counter(n=1), one(), Absent(spare)]),
)
create_once = Scenario(
    action=create,
    given=[Limit(max_created=1), Counter(), Absent(one), Absent(spare)],
    then=[Present(one), Counter.n == 1],
)
noise_once = Scenario(action=flip_noise, given=[Noise()], then=[Noise.on])

spec = Spec(
    id="fixed_initial",
    name="Fixed initial world",
    initial=Initial(given=[Limit(max_created=1), Absent(one), Absent(spare)]),
    actions=[create, flip_noise],
    scenarios=[create_once, noise_once],
    invariants=[balanced],
    queries=[created, already_created],
)
```

The canonical whole-model graph has one root and four states; the invariant and
`created` each need only two states in their slices. Use `analint trace created`
with `-p .` for the `create` witness, or `analint trace already_created -p .` for
the query-specific initial-state witness.

## Event and Emitted

`Event` uses typed fields like Entity. `Action.emits` accepts an event class or a
payload template whose fields bind to state expressions:

```python
from analint import Emitted, Event


class PaymentRecorded(Event):
    amount: int


# On an action: emits=[PaymentRecorded(amount=Order.total)]
# In Scenario.then or Flow.steps: Emitted(PaymentRecorded)
```

Payload templates are type-checked and materialized against the post-state. Emission
does not dispatch another action. A scenario can supply an Event instance in
`given` to test an action with payload preconditions; such external inputs are
not generated by reachability exploration. They are reported as unassessed.

## Scenario and Flow

`Scenario(action=..., given=[...], then=[...], expected=Expect.PASS)` checks one
action. `then` accepts predicates and `Emitted` checks. `Expect.FAIL` expects
pre-execution rejection, not a runtime defect.

`Flow(given=[...], steps=[...])` executes a journey. Steps mix actions with
`Assert(predicate)` and `Emitted(EventClass)` checkpoints. `given` is required;
`given=[]` starts with an empty world. Only present instances are available, and
each accepted step's state feeds the next step. A rejection or defect fails the
flow. Both declarations accept ids and descriptive metadata; the tutorial shows
complete examples.

## Queries

| Declaration | Requirement |
| --- | --- |
| `Reachable(predicate)` | A matching state can be reached from each root |
| `Unreachable(predicate)` | No matching state can be reached |
| `AlwaysHolds(predicate)` | The predicate holds in every applicable reachable state |
| `NoDeadEnd(goal=predicate)` | A goal state remains reachable from every reachable state |
| `DeadActions()` | Assess which actions can never fire in the explored model |

Each accepts `id`, `label`, `max_states` and one optional initial source:
`given`, `given_any` or `initial`. Queries with none inherit the canonical roots.
NoDeadEnd is recoverability, not a guarantee that every execution terminates.
Excluded event-input actions are unassessed, not dead.

## Spec, Contract and loading

`Spec(id=..., name=..., actions=[...], invariants=[...], scenarios=[...],
flows=[...], queries=[...])` is the root. It can additionally list entities, events,
scopes and lifecycles, which are otherwise derived from referenced behaviour.
`Spec.initial` supplies canonical roots; `Spec.max_states` sets the canonical
exploration budget (default 10,000).

`Contract(id=..., actions=[...], ...)` is an explicit reusable fragment with the
same content lists. `Spec(imports=[contract, ...], ...)` combines those lists
with the root's own. Contract `version` is descriptive metadata, not a resolver
that downloads dependencies.

Load one entry point: a `spec.py` directory or an explicit Python file. Multi-file
models should be packages with `__init__.py` and relative imports. List behaviour
explicitly: merely importing a file does not register its actions or properties.
The loader names empty ids from variable names, warns about unlisted behaviour
and unreachable files, and rejects multiple Spec roots in one import graph.
An empty behaviour model is an error.

The [taskboard](examples.md) and broker examples show composition. Use
`analint show contract ID -p PATH` to inspect a contract's public surface.
