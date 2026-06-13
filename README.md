# analint

**A Python DSL for declaring and verifying how a system behaves.**

Requirements live in Word, Confluence, and Miro — readable by humans, but impossible to check for contradictions, diff, or hand to an AI agent. Code is the other extreme: too low-level. analint sits in the middle: **Python that reads like a specification and checks like one.**

```python
checkout = Action(
    by=Customer,
    pre=[
        Wallet.balance >= Order.total,
        Order.status == OrderStatus.PENDING,
    ],
    effect=[
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),
    ],
)

sc_broke = Scenario(
    name="Insufficient balance",
    action=checkout,
    given=[
        Order(id="o1", total=50.0, customer_id="c1"),
        Wallet(balance=10.0, customer_id="c1"),  # 10 < 50 → blocked
    ],
    expected=Expect.FAIL,
)
```

```
analint examples/ecommerce/

SCENARIOS
  PASS  checkout/happy           (6 rules)
  PASS  checkout/no-funds        (6 rules)
         ↳  PRE failed: Wallet.balance >= Order.total
         ↳  correctly blocked — rules rejected this data as expected
```

It is not limited to business analytics: the same primitives describe game rules and narrative consistency — see [`examples/cloak/`](examples/cloak/spec.py), the classic *Cloak of Darkness* IF benchmark expressed as a verifiable spec.

---

## Installation

```bash
pip install analint
# or with uv:
uv add analint
```

---

## Quick start

Create `spec.py` and run `analint .` in the same directory.

```python
from analint import Entity, Action, Scenario, Spec, Expect

class Item(Entity):
    price: float
    stock: int

class Budget(Entity):
    amount: float

buy = Action(
    pre=[
        Item.price > 0,
        Budget.amount >= Item.price,
    ],
)

sc_ok = Scenario(
    name="Happy path",
    action=buy,
    given=[Item(price=10.0, stock=5), Budget(amount=20.0)],
)

spec = Spec(id="shop", name="Shop")   # everything above is discovered automatically
```

ids are derived from variable names (`buy`, `sc_ok`) — set `id=` explicitly only when you want a different one.

---

## DSL reference

The DSL has three layers: **state** (Entity, Actor, Event), **constraints** (Invariant, predicates), and **transitions** (Action, Lifecycle). Scenarios and Flows tie them together with concrete examples.

### Entity

Typed system state. Annotate fields normally; class-level access returns a
`FieldDescriptor` usable in predicate expressions. Use `Field(...)` for
constraints on one value, and attach a `Lifecycle(...)` directly to a field
whose states have declared transitions.

```python
from enum import StrEnum
from analint import Entity, Field, Lifecycle, Transition

class OrderStatus(StrEnum):
    PENDING   = "pending"
    PAID      = "paid"
    CANCELLED = "cancelled"

class Order(Entity):
    status: OrderStatus = Lifecycle(
        initial=OrderStatus.PENDING,
        transitions=[
            Transition(OrderStatus.PENDING, [OrderStatus.PAID, OrderStatus.CANCELLED]),
            Transition(OrderStatus.PAID, [OrderStatus.CANCELLED]),
        ],
        terminal=[OrderStatus.CANCELLED],
    )
    total: float = Field(gt=0)                 # required, must be positive
    customer_id: str

Order.total                           # class level → FieldDescriptor (for predicates)
Order(total=50.0, customer_id="c1").total   # instance level → 50.0
```

`Field(default, ge=..., gt=..., le=..., lt=...)` validates constructed
instances, checks post-action values, and supplies finite numeric bounds to the
reachability engine. `Field(default, values=[...])` declares an explicit
finite scalar domain. With `saturate=True`, numeric values clamp at the
declared `ge`/`le` thresholds instead of making the transition invalid.

### Predicates

Comparison operators on fields build predicate objects; combinators are plain functions:

```python
Order.total > 0
Order.status == OrderStatus.PENDING
Wallet.balance >= Order.total          # field-to-field comparison

from analint import And, Or, Not, Implies, In, IsNull, IsNotNull

And(Order.total > 0, Wallet.balance >= Order.total)
Implies(Hook.holds_cloak == True, Player.has_cloak == False)   # if A then B
In(Order.status, [OrderStatus.PAID, OrderStatus.CANCELLED])
```

Arithmetic over fields builds expression nodes — including named, reusable
ones (Quint-style derived values):

```python
Wallet.balance - Order.total >= 0
total_supply = Alice.coins + Bob.coins + Eve.coins   # named expression
supply_fits  = AlwaysHolds(total_supply <= MAX_SUPPLY)
```

Predicates are values — name them and reuse them:

```python
board_is_active = Board.status == BoardStatus.ACTIVE

create_card  = Action(pre=[board_is_active, ...])
archive_card = Action(pre=[board_is_active, ...])
```

### Invariant

A relation that must hold in **every** state — checked before an action and
re-checked after its effects. Put constraints involving one field on
`Field(...)`; use `Invariant` for relationships between fields or entities.

```python
from analint import Implies, Invariant

delivered_means_paid = Invariant(
    Implies(
        Order.status == OrderStatus.DELIVERED,
        Payment.status == PaymentStatus.CAPTURED,
    ),
    label="A delivered order must have a captured payment",
)
```

An invariant is skipped in scenarios whose `given` does not include the entities it references.

### Action

A state transition: what must hold before (`pre`), what changes (`effect`),
what must hold after (`post`), plus optional documentation about actor,
ordering and events.

```python
from analint import Action, Set, Subtract

checkout = Action(
    name="Customer Checkout",
    by=Customer,                                   # Actor metadata (not an auth guard)
    pre=[
        Wallet.balance >= Order.total,
        Product.stock > 0,
        Order.status == OrderStatus.PENDING,
    ],
    effect=[                                       # facts about the next state
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),
        Subtract(Product.stock, 1),
    ],
    post=[Order.status == OrderStatus.PAID],       # optional double-entry check
    emits=[OrderPlaced(order_id=Order.id, total=Order.total, customer_id=Order.customer_id)],
    requires=[login],                              # Flow-ordering documentation
)
```

**Effects are simultaneous facts, not a program.** Every right-hand side is evaluated against the *pre*-state; the order of the list carries no meaning; two effects on the same field are a structural error.

Current semantic boundary: `by` does not affect enabledness, `requires` is
checked only against declared `Flow` order, and `on` does not create an event
queue or gate exploration. Authorization belongs in explicit parameters and
`pre`; operational event semantics is a planned design decision.

| Effect | Next-state fact |
|---|---|
| `Set(field, value)` | field becomes the value — a literal, an enum, or an **expression over the pre-state**: `Set(src.coins, src.coins - amount)` is the canonical form |
| `Subtract(field, amount)` / `Add(field, amount)` | sugar for `Set(field, field ∓ amount)` |
| `Create(ref, **fields)` / `Delete(ref)` | a slot in a `Scope` becomes present / absent — presence as a next-state fact (see [Bounded multiplicity](#bounded-multiplicity)) |

#### Parameterized actions

A family of similar transitions is one declaration over finite domains —
never a host-language loop:

```python
from analint import Param

src    = Param("src", AliceCoins, BobCoins, EveCoins)
dst    = Param("dst", AliceCoins, BobCoins, EveCoins)
amount = Param("amount", ge=1, le=3)   # integer range — same vocabulary as Field

send = Action(
    params=[src, dst, amount],
    where=[src != dst],
    pre=[src.coins >= amount, dst.coins <= MAX_BALANCE - amount],
    effect=[Subtract(src.coins, amount), Add(dst.coins, amount)],
)
```

The engine expands every binding that satisfies `where` into a concrete
action (`send(src=AliceCoins, dst=BobCoins, amount=2)`); traces and reports
use the parametric names. A scenario picks one binding:
`action=send.bind(src=BobCoins, dst=EveCoins, amount=2)`.

#### Bounded multiplicity

`Scope` declares a fixed finite set of identified instances of one entity
type. Instance refs work in predicates and effects, and can be a `Param`
domain:

```python
from analint import Absent, Present, Scope

class Account(Entity):
    balance: int = Field(0, ge=0, le=5)

accounts = Scope(Account, keys=["alice", "bob", "eve"])
alice = accounts["alice"]

src = Param("src", accounts)
dst = Param("dst", accounts)

transfer = Action(
    params=[src, dst],
    where=[src != dst],
    pre=[src.balance >= 1],
    effect=[Subtract(src.balance, 1), Add(dst.balance, 1)],
)

alice_pays_bob = Scenario(
    action=transfer.bind(src=alice, dst=accounts["bob"]),
    given=[
        alice(balance=3),
        accounts["bob"](balance=0),
        Absent(accounts["eve"]),
    ],
)

alice_exists = Present(alice)
```

The universe is fixed, but membership is explicit. A normal scoped snapshot is
present; `Absent(ref)` marks an allocated slot as absent; `Present(ref)` is a
predicate usable in guards and queries. In scenarios, omitted scoped slots are
also absent. Reachability defaults every scoped slot to present unless
`given=[Absent(ref)]` says otherwise. Field reads and ordinary effects on an
absent slot are rejected.

`Create(ref, **fields)` and `Delete(ref)` change that membership as next-state
facts, symmetric to `Set` over a value:

```python
from analint import Create, Delete

open_account = Action(effect=[Create(accounts["eve"], balance=0)])  # eve must be absent
close_account = Action(effect=[Delete(alice)])                       # alice must be present
```

`Create` requires the slot absent and makes it present (unspecified fields take
their defaults); `Delete` requires it present and makes it absent. The
mismatched pre-state is rejected before any effect runs, so `Expect.FAIL`
covers it. A slot's presence may change at most once per action, and the same
slot may not be both (de)allocated and written by `Set`/`Add`/`Subtract`. The
key universe stays fixed, so reachability, quantifiers and aggregates simply
range over whichever slots are present in each state.

#### Finite quantifiers

`Bound` introduces a named variable over a `Scope`; `ForAll` and `Exists`
remain explicit predicate AST nodes and work in invariants, action guards,
scenario assertions, and reachability queries:

```python
from analint import Bound, Count, Exists, ForAll, Max, Min, Sum

account = Bound("account", accounts)

all_balances_valid = AlwaysHolds(
    ForAll(account, account.balance >= 0)
)

someone_is_full = Reachable(
    Exists(account, account.balance == 5)
)

total_balance = Sum(account, account.balance)
nonempty_accounts = Count(account, account.balance > 0)
balance_range = Max(account, account.balance) - Min(account, account.balance)
```

Quantifiers and aggregates are finite and exhaustive over the **present**
instances in the registered scope. Aggregate nodes are ordinary arithmetic
expressions: they can be compared, composed with field math, used in effect
right-hand sides, and checked by the reachability engine. Over an empty
present set, `ForAll` is true, `Exists` is false, `Count` and `Sum` are zero,
while `Min`/`Max` report an evaluation error.

### Actor

Who can trigger an action. Subclass `Actor` to define a role:

```python
from analint import Actor

class Customer(Actor): pass
class Admin(Actor): pass
```

### Event

A signal between actions, with a typed payload. Emitting binds payload fields to expressions over the state; `on=` subscribes an action to an event, and its `pre` may constrain the payload:

```python
from analint import Event

class OrderPlaced(Event):
    order_id: str
    total: float

checkout = Action(..., emits=[OrderPlaced(order_id=Order.id, total=Order.total)])

notify_vip = Action(
    on=OrderPlaced,
    pre=[OrderPlaced.total > 100],     # payload condition
    effect=[Add(Manager.alerts, 1)],
)
```

The linter validates payload bindings (fields exist, types match) and warns when
an emitted event is not referenced by any action's `on` metadata. `on` does not
yet define executable event-delivery semantics.

### Lifecycle

Valid states of an entity field and the allowed transitions between them.
The lifecycle is declared as the field's default, so the state definition,
initial value, transitions, and terminal states stay together.

```python
class Order(Entity):
    status: OrderStatus = Lifecycle(
        initial=OrderStatus.PENDING,
        transitions=[
            Transition(OrderStatus.PENDING, [OrderStatus.PAID, OrderStatus.CANCELLED]),
            Transition(OrderStatus.PAID, [OrderStatus.CANCELLED]),
        ],
        terminal=[OrderStatus.CANCELLED],
    )
```

`terminal` states have teeth: an entity whose lifecycle field is in a terminal state cannot be modified by any action, and a transition out of a terminal state is a structural error.

### Scenario

A concrete example: initial state, one action, expected outcome.

```python
from analint import Scenario, Expect, Assert, Emitted

sc_happy = Scenario(
    name="Successful purchase",
    action=checkout,
    given=[
        Order(id="o1", total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],
    then=[
        Assert(Order.status == OrderStatus.PAID),
        Assert(Wallet.balance == 50.0),
        Emitted(OrderPlaced),
    ],
    expected=Expect.PASS,
)
```

`expected=Expect.FAIL` documents a blocked path: the scenario is **correct** when at least one rule rejects the data.

For an event-payload scenario, put the event instance in `given` — its payload
is then visible to `pre`. This checks one local transition; `on=` itself is not
an operational trigger:

```python
Scenario(action=notify_vip, given=[OrderPlaced(order_id="o1", total=500.0), Manager(alerts=0)])
```

### Flow

An ordered journey declaration. It is currently structural documentation: the
linter verifies `requires` order, but does not execute state through the steps.

```python
from analint import Flow

purchase_flow = Flow(
    steps=[login, browse, checkout],
    description="Full customer purchase journey",
)
```

### Reachability queries

Scenarios check states you thought of. Queries **explore every reachable state** (BFS over the model) and answer questions you can't answer by hand — each verdict comes with a trace:

```python
from analint import Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions

bridge_is_reachable = Reachable(Quest.bridge_crossed == True)
no_softlock         = NoDeadEnd(goal=Quest.bridge_crossed == True)
hp_never_negative   = AlwaysHolds(Hero.hp >= 0)
no_gold_from_air    = Unreachable(Hero.gold > 6)     # regression guard
every_action_used   = DeadActions()
```

```
QUERIES
  PASS  bridge_is_reachable        (Reachable, 9 states)
         ↳ reachable: buy_sword → fight_troll → cross_bridge
  FAIL  no_softlock                (NoDeadEnd, 9 states)
         ↳ dead end: after buy_potion the goal can no longer be reached
  FAIL  hp_never_negative          (AlwaysHolds, 9 states)
         ↳ breaks: buy_sword → fight_troll → cross_bridge ⇒ Hero.hp=-1
```

The softlock above is invisible to every scenario in the spec — nobody writes a test for a situation they didn't think of. The explorer finds it in milliseconds with the shortest trace.

- The **initial state** is built from entity field defaults; `given=[...]`
  supplies or overrides instances. `given_any=[[...], [...]]` declares an
  explicit finite set of roots.
- `initial=Initial(vary=[...], where=[...])` declares an initial relation.
  `vary` fields range over `bool`, `Enum`, bounded integer `Field`, or
  `Field(values=[...])` domains; ordinary predicates filter the Cartesian
  product. `BoundField` varies a field across an entire `Scope`.
- Queries quantify over every admissible root, and traces name the originating
  configuration (`init #2 ⊢ …`).
- Numeric `Field(ge=..., le=...)` constraints keep the state space finite.
  Driving a field out of range is an error with a trace; `saturate=True`
  clamps instead, for counters where only thresholds matter.
- If the state space exceeds `max_states` (default 10 000), the query reports **INCONCLUSIVE** instead of pretending.
- During exploration the engine also reports **violated invariants** and **undeclared lifecycle transitions** (an effect performing `A → C` when the lifecycle only allows `A → B`).
- An ad-hoc query without editing the spec: put it in a file and run `analint check . --what-if query.py`.

```python
from analint import Bound, Count, Initial

player = Bound("player", players)
role_assignments = Initial(
    vary=[player.role],
    where=[Count(player, player.role == Role.MAFIA) == 1],
)

mafia_can_win = Reachable(Game.winner == Role.MAFIA, initial=role_assignments)
```

### Spec

The root aggregate — usually just metadata:

```python
from analint import Spec

spec = Spec(id="ecommerce", name="E-commerce Platform")
```

Everything else is discovered from the modules your entry point imports. Explicit lists (`entities=[...]`, `actions=[...]`) are supported when precision matters; a non-empty list is used as-is.

### Composition

Reusable model fragments expose an explicit `Contract`; one root `Spec`
imports those contracts:

```python
# payments.py
from analint import Contract

payments_api = Contract(
    id="payments",
    version="1.0.0",
    entities=[Payment],
    events=[PaymentCaptured],
    invariants=[payment_amount_is_positive],
    actions=[capture_payment],
)

# spec.py
from analint import Spec
from .payments import payments_api

spec = Spec(
    id="checkout",
    name="Checkout",
    imports=[payments_api],
    scenarios=[capture_payment_happy],
)
```

Composition is deliberately explicit: when `imports=` is present,
auto-discovery is disabled for the root. Only contract contents and objects
listed directly on `Spec` are included, so private implementation actions do
not leak through Python's import graph. Duplicate ids and incomplete contract
surfaces are reported by structural validation. Multiple `Spec` objects in one
import graph are a load error rather than being merged implicitly.

`analint show contract payments -p .` reports the exact exported surface.
`--what-if` still adds hypothesis objects on top of the composed model.

---

## Project layout

The spec is loaded through a **single entry point** — `spec.py` — and its import graph defines what is in the spec:

```
spec.py             ← single file is enough for small projects

# or, multi-file (use relative imports):
myproject/
  __init__.py
  entities.py       ← Entity subclasses + enums
  actors.py         ← Actor subclasses
  events.py         ← Event subclasses
  invariants.py     ← Invariant instances + reusable predicates
  actions.py        ← Action instances
  flows.py          ← Flow instances
  scenarios.py      ← Scenario instances
  spec.py           ← imports the tops of the graph + Spec(id=..., name=...)
```

```python
# myproject/spec.py
from analint import Spec
from . import flows, scenarios  # noqa: F401

spec = Spec(id="myproject", name="My Project")
```

A `.py` file in the directory that is not reachable from the entry point produces a warning — a forgotten import never silently shrinks the model.

---

## CLI

```
analint check [PATH]              # validate: structural checks + scenario runs
  -f, --format terminal|json
  -s, --scenario ID   -t, --tag TAG
  --strict                        # warnings become errors
  --what-if FILE.py               # add the file's objects to the model for this
                                  # run only — test a hypothesis without editing the spec

analint show [KIND] [NAME] -p PATH   # inspect the model (JSON output)
  analint show -p .                  # overview: all ids by kind
  analint show contract payments -p . # exact imported contract surface
  analint show action checkout -p .  # pre/effect/post/emits/scenarios of one action
  analint show lifecycle Order.status -p .      # transitions, terminal, unreachable states

analint affects TARGET -p PATH    # impact analysis before changing something (JSON)
  analint affects Wallet.balance -p .   # who reads/writes the field, invariants, lifecycles
  analint affects checkout -p .         # what the action touches + event-linked actions

analint PATH                      # shorthand for `analint check PATH`
```

Exit codes: `0` ok · `1` findings (errors, failed scenarios, warnings with `--strict`) · `2` usage error · `3` spec could not be loaded · `4` inconclusive (a query exhausted its exploration budget without a verdict). JSON output carries a three-valued `verdict` (`PASS`/`FAIL`/`INCONCLUSIVE`); `passed` is `true` only on an effective `PASS` and reflects `--strict`.

### What-if: check a hypothesis without touching the spec

```python
# /tmp/hypothesis.py
from analint import Invariant
from myproject.entities import Board

max_two = Invariant(Board.card_count <= 2, label="At most 2 cards per board")
```

```
analint check . --what-if /tmp/hypothesis.py
  FAIL  archive-card/happy
         ↳  INVARIANT failed: At most 2 cards per board
```

### MCP server (for AI agents)

```bash
pip install analint[mcp]
analint-mcp        # stdio MCP server with tools: check, show, affects
```

The same three operations as the CLI, callable as agent tools — an agent can inspect the model, run impact analysis before a change, test a hypothesis with `what_if`, and validate after editing.

---

## What the linter checks

### Structural

- Missing/duplicate ids; duplicate class names from double imports
- Predicates reference registered entities/events and existing fields
- `by` actors registered; `requires` graphs acyclic; flow order satisfies `requires`
- Event payload bindings: fields exist, annotation types match
- Emitted events are handled by at least one `on=` (warning if not)
- Two effects on the same field (simultaneity violation)
- Field constraints on construction and after effects
- Transitions out of `terminal` states
- Scenario `given` covers the entities the action references (warning)
- Scenario `given` states reachable from the lifecycle initial state (warning)
- Actions without scenarios (warning); files not imported by the entry point (warning)

### Scenario execution

1. **Invariants** and **pre** — checked against `given`
2. **Terminal guard** — an entity in a terminal lifecycle state must not be modified
3. **Effects** applied simultaneously → post-state
4. **post**, invariants, and field constraints — checked against the post-state
5. **then** (`Assert`, `Emitted`) — checked against the post-state

If `expected=Expect.FAIL`: the scenario passes when steps 1–2 block the action.

### Reachability (queries)

BFS over all reachable states; every query answers with a trace of action ids:

- `Reachable(p)` — a witness path exists / FAIL with "explored all N states"
- `Unreachable(p)` — regression guard; FAIL shows the counterexample path
- `AlwaysHolds(p)` — invariant over the whole space, not just scenarios
- `NoDeadEnd(goal)` — softlock detector: a reachable state from which the goal is gone
- `DeadActions()` — actions never enabled in any reachable state
- en route: invariant violations and undeclared lifecycle transitions, with traces

---

## Examples

| Example | What it shows |
|---|---|
| [`examples/ecommerce/`](examples/ecommerce/spec.py) | Single file: invariants, pre/post, effects, payload-bound events, Reachable with `given` |
| [`examples/taskboard/`](examples/taskboard/) | Multi-file spec: 7 entities, 8 actions, 16 scenarios, lifecycles with terminal states, event-driven actions |
| [`examples/cloak/`](examples/cloak/spec.py) | A text-adventure game as a verifiable spec: the engine finds the walkthrough (`Reachable(WON)`), proves you can't get stuck (`NoDeadEnd`) |
| [`examples/trollbridge/`](examples/trollbridge/spec.py) | **Deliberately broken**: all scenarios green, but the engine finds an economy softlock and an unmodelled death — bugs example-based testing cannot see |
| [`examples/fulfillment/`](examples/fulfillment/) | An order-fulfillment **saga** as a pure domain model: 16 actions with compensations for every failure, `NoDeadEnd` proves no order ever wedges with money or goods stuck |
| [`examples/coin/`](examples/coin/spec.py) | A line-by-line translation of **Quint's flagship tutorial** (the Solidity subcurrency) — reproduces the supply-overflow violation from the Quint lesson with a trace; see `research/15` for the honest comparison |
