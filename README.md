# analint

**A Python DSL for declaring and verifying business analytics.**

Business requirements live in Word, Confluence, and Miro — readable by humans, but impossible to check for contradictions, diff, or pass to an agent. Code is the other extreme: too low-level, too technical. analint sits in the middle: **Python code that reads like requirements and validates like a specification.**

```python
rule_funds = BusinessRule(
    id="sufficient-funds",
    name="Wallet balance must cover order total",
    rule_type=RuleType.PRECONDITION,
    expression=Wallet.balance >= Order.total,
)

sc_broke = Scenario(
    id="checkout/no-funds",
    name="Insufficient balance",
    use_case=uc_checkout,
    given=[
        Order(total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=10.0, customer_id="c1"),  # 10 < 50 → rule fails
    ],
    expected=Expect.FAIL,
)
```

```
analint examples/ecommerce/

SCENARIOS
  PASS  checkout/happy           (5 rules)
  PASS  checkout/no-funds        (5 rules)
         ↳  PRECONDITION 'Wallet balance must cover order total' failed:
            Wallet.balance >= Order.total
         ↳  correctly blocked — rules rejected this data as expected
```

---

## Installation

```bash
pip install analint
# or with uv:
uv add analint
```

---

## Quick start

Create a file (e.g. `spec.py`) and run `analint .` in the same directory.

```python
from analint import Entity, BusinessRule, UseCase, Scenario, Spec, Expect

class Item(Entity):
    price: float
    stock: int

class Budget(Entity):
    amount: float

rule_price  = BusinessRule(id="price-positive", name="Item price must be positive",
                           expression=Item.price > 0)
rule_budget = BusinessRule(id="budget-covers",  name="Budget covers item price",
                           expression=Budget.amount >= Item.price)

uc_buy = UseCase(id="buy", name="Buy item",
                 entities=[Item, Budget], rules=[rule_price, rule_budget])

sc_ok = Scenario(id="buy/ok", name="Happy path", use_case=uc_buy,
                 given=[Item(price=10.0, stock=5), Budget(amount=20.0)],
                 expected=Expect.PASS)

spec = Spec(id="shop", name="Shop")  # loader discovers entities, rules, use cases, scenarios automatically
```

---

## DSL reference

### Entity

Domain objects. Annotate fields normally; class-level access returns a `FieldDescriptor` that can be used in predicate expressions.

```python
from analint import Entity
from enum import Enum

class OrderStatus(Enum):
    PENDING   = "pending"
    PAID      = "paid"
    CANCELLED = "cancelled"

class Order(Entity):
    status: OrderStatus = OrderStatus.PENDING  # field with default
    total: float                               # required field
    customer_id: str

class Wallet(Entity):
    balance: float
    customer_id: str

# Class-level → FieldDescriptor (used in rules)
Order.total          # FieldDescriptor

# Instance-level → value
order = Order(total=50.0, customer_id="c1")
order.total          # 50.0
```

### Actor

Marks who can trigger a use case. Subclass `Actor` to define a role.

```python
from analint import Actor

class Customer(Actor): pass
class Admin(Actor): pass
```

### Event

Domain events emitted by use cases. Fields work the same as Entity.

```python
from analint import Event

class OrderPlaced(Event):
    order_id: str
    total: float
    customer_id: str
```

### BusinessRule

A verifiable rule with three lifecycle types:

| Type | When checked | Example |
|---|---|---|
| `INVARIANT` | Always, in every scenario | `Product.price > 0` |
| `PRECONDITION` | Before use case executes | `Wallet.balance >= Order.total` |
| `POSTCONDITION` | After effects are applied | `Order.status == OrderStatus.PAID` |

```python
from analint import BusinessRule, RuleType

rule_funds = BusinessRule(
    id="sufficient-funds",
    name="Wallet balance must cover order total",
    rule_type=RuleType.PRECONDITION,
    expression=Wallet.balance >= Order.total,
)

rule_paid = BusinessRule(
    id="order-paid",
    name="Order must be paid after checkout",
    rule_type=RuleType.POSTCONDITION,
    expression=Order.status == OrderStatus.PAID,
)
```

#### Predicate operators

All comparison operators on `FieldDescriptor` return predicate objects:

```python
Order.total > 0          # _Gt
Order.total >= 0         # _Gte
Order.total < 1000       # _Lt
Order.total <= 1000      # _Lte
Order.status == OrderStatus.PENDING  # _Eq
Order.status != OrderStatus.CANCELLED  # _Ne

# Logical combinators (keywords can't be overloaded in Python)
from analint import And, Or, Not, In, IsNull, IsNotNull

And(Order.total > 0, Wallet.balance >= Order.total)
Or(Order.status == OrderStatus.PAID, Order.status == OrderStatus.CANCELLED)
Not(Order.status == OrderStatus.PENDING)
In(Order.status, [OrderStatus.PAID, OrderStatus.CANCELLED])
IsNull(Order.customer_id)
IsNotNull(Order.customer_id)
```

### UseCase

Describes a business operation: who does it, what data it touches, what rules apply, what it changes, and what it emits.

```python
from analint import UseCase, Set, Subtract

uc_checkout = UseCase(
    id="checkout",
    name="Customer Checkout",
    description="Customer places an order; all preconditions must hold",

    actor=Customer,                                    # who triggers this UC
    entities=[Order, Wallet, Product],                 # entity types involved

    rules=[rule_funds, rule_stock, rule_pending, rule_paid],

    requires=[uc_login],                               # must execute before this UC
    emits=[OrderPlaced],                               # events published on success
    triggered_by=[CartFinalized],                      # events that trigger this UC

    effects=[                                          # state changes applied after preconditions pass
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),         # amount can be a FieldDescriptor
        Subtract(Product.stock, 1),
    ],
)
```

**Effects** are applied in order after all preconditions pass. Available effect types:

| Effect | Description |
|---|---|
| `Set(field, value)` | Set field to a fixed value or enum |
| `Subtract(field, amount)` | Subtract amount (literal or FieldDescriptor) from field |
| `Add(field, amount)` | Add amount (literal or FieldDescriptor) to field |

### StateMachine

Describes the lifecycle of an entity field — valid states and which transitions are allowed.

```python
from analint import StateMachine, Transition

order_lifecycle = StateMachine(
    id="order-lifecycle",
    field=Order.status,
    initial=OrderStatus.PENDING,
    transitions=[
        Transition(OrderStatus.PENDING, [OrderStatus.PAID, OrderStatus.CANCELLED]),
        Transition(OrderStatus.PAID,     OrderStatus.CANCELLED),
    ],
)

order_lifecycle.reachable_states()
# {OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.CANCELLED}
```

`Transition(from_state, to_states)` — the second argument can be a single value or a list.

### Scenario

A concrete test case: initial data and expected post-conditions.

```python
from analint import Scenario, Expect, Assert, Emitted

sc_happy = Scenario(
    id="checkout/happy",
    name="Successful purchase",
    use_case=uc_checkout,

    given=[
        Order(total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],

    then=[                          # assertions checked after effects are applied
        Assert(Order.status == OrderStatus.PAID),
        Assert(Wallet.balance == 50.0),
        Emitted(OrderPlaced),       # verify event is declared in use_case.emits
    ],

    expected=Expect.PASS,           # or Expect.FAIL — inverts the pass/fail logic
)
```

`expected=Expect.FAIL` means the scenario is **correct** when at least one rule fails — useful for documenting blocked paths and rejected data.

### Flow

Describes a linear user journey as an ordered list of use cases. The linter verifies that `requires` constraints are satisfied by the step order.

```python
from analint import Flow

flow_purchase = Flow(
    id="purchase-flow",
    steps=[uc_login, uc_browse, uc_checkout],  # uc_checkout requires uc_login → must come after
    description="Full customer purchase journey",
)
```

### Spec

The root aggregate that the linter reads. For single-directory projects the loader discovers everything automatically — just provide the metadata:

```python
from analint import Spec

# minimal — loader discovers entities, rules, use cases, scenarios, etc. from all .py files
spec = Spec(id="ecommerce", name="E-commerce Platform")
```

Explicit lists are supported when you need precision (e.g. multiple specs in one directory, or when you want to exclude some items):

```python
spec = Spec(
    id="ecommerce",
    name="E-commerce Platform",
    version="0.8.0",

    entities=[Order, Wallet, Product],
    actors=[Customer, Admin],
    events=[OrderPlaced],
    state_machines=[order_lifecycle],
    flows=[flow_purchase],

    rules=[rule_funds, rule_stock, rule_pending, rule_paid],
    use_cases=[uc_checkout],
    scenarios=[sc_happy, sc_no_funds, sc_no_stock, sc_already_paid],
)
```

Rule: if a list is non-empty in `Spec(...)`, it is used as-is. If a list is empty (the default), it is auto-populated from all discovered modules.

---

## CLI

```
analint [PATH] [OPTIONS]

Arguments:
  PATH    Directory to discover spec files in (default: .)

Options:
  -f, --format TEXT     Output format: terminal (default) or json
  -s, --scenario TEXT   Run only this scenario id (repeatable)
  -t, --tag TEXT        Run only scenarios with this tag (repeatable)
  --strict              Treat warnings as errors
  --fail-fast           Stop after first failure
```

```bash
analint examples/ecommerce/            # run all scenarios
analint . --format json                # machine-readable output
analint . --scenario checkout/happy    # single scenario
analint . --strict                     # warnings become errors
```

---

## What the linter checks

### Structural

- Duplicate ids in rules, use cases, scenarios, state machines, flows
- `FieldDescriptor` references point to registered entities with existing fields
- `UseCase.entities` and `UseCase.rules` are registered in `Spec`
- `UseCase.actor` subclasses `Actor` and is registered in `Spec.actors`
- `UseCase.requires` — all referenced use cases registered; no circular dependencies
- `UseCase.emits` / `triggered_by` — events registered in `Spec.events`
- Emitted events are handled by at least one `triggered_by` (warning if not)
- `StateMachine.entity` registered in `Spec.entities`
- Scenario `given` covers all entity types referenced by rules (warning if not)
- Scenario `given` state is reachable from state machine initial (warning if not)
- `Flow` steps are registered use cases; `requires` order is respected
- `UseCase.effects` target registered entities

### Scenario execution

For each scenario:

1. **Invariants** — checked against `given` state
2. **Preconditions** — checked against `given` state
3. **Effects** applied — produces post-state
4. **Postconditions** — checked against post-state
5. **Then assertions** (`Assert`, `Emitted`) — checked against post-state

If `expected=Expect.FAIL`: the scenario passes when any rule in steps 1–2 fails.

---

## Example output

```
analint v0.8.0  spec: E-commerce Platform

STRUCTURAL
  WARN    event 'OrderPlaced' is emitted but never triggers a use_case

SCENARIOS
  PASS  checkout/happy                           (5 rules)
  PASS  checkout/no-funds                        (5 rules)
         ↳  PRECONDITION 'Wallet balance must cover order total' failed:
            Wallet.balance >= Order.total
         ↳  correctly blocked — rules rejected this data as expected
  PASS  checkout/out-of-stock                    (5 rules)
         ↳  PRECONDITION 'Product must have stock' failed: Product.stock > 0
         ↳  correctly blocked — rules rejected this data as expected
  PASS  checkout/already-paid                    (5 rules)
         ↳  PRECONDITION 'Order must be in pending status to check out' failed:
            Order.status == OrderStatus.PENDING
         ↳  correctly blocked — rules rejected this data as expected

Results: 4 passed, 1 warnings
```

---

## Project layout

For small projects a single file is enough:

```
spec.py             ← all entities, rules, use cases, scenarios, and Spec(id=..., name=...)
```

For larger projects, split by concern — the loader discovers and assembles everything automatically:

```
myproject/
  entities.py       ← Entity subclasses + enums
  actors.py         ← Actor subclasses
  events.py         ← Event subclasses
  rules.py          ← BusinessRule instances
  use_cases.py      ← UseCase instances
  state_machines.py ← StateMachine instances
  flows.py          ← Flow instances
  scenarios.py      ← Scenario instances
  spec.py           ← Spec(id="myproject", name="My Project") — metadata only
```

analint discovers all Python files in the given directory, imports them, and auto-populates the `Spec` from everything it finds. If you set a list explicitly in `Spec(...)`, that list is used as-is (opt-in override for precision or multiple-spec directories).
