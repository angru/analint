# AGENTS.md — analint

Context for AI agents working in this repository.

## What this project is

analint is a **Python DSL for declaring and verifying business analytics**. It lets you describe domain entities, business rules, use cases, and scenarios as Python code — then validates that the rules hold against concrete data.

It is NOT an architecture linter, NOT a service topology tool. It is a business-logic specification framework.

The central idea: business rules are declared as predicate expressions over entity fields (`Wallet.balance >= Order.total`), scenarios provide concrete entity instances, and the linter evaluates whether rules pass or fail against that data.

---

## Repository layout

```
src/analint/
  __init__.py               ← public API — all user-facing symbols exported here
  cli.py                    ← typer CLI entry point

  models/
    entity.py               ← Entity base class, EntityMeta metaclass, FieldDescriptor
    actor.py                ← Actor base class (role markers)
    event.py                ← Event base class (same metaclass as Entity)
    predicate.py            ← _Eq, _Gte, _And, _Not … dataclasses + And/Or/Not factories
    business.py             ← BusinessRule, UseCase (with effects, emits, requires)
    scenario.py             ← Scenario, Expect enum
    statemachine.py         ← StateMachine, Transition dataclasses
    effect.py               ← Set, Subtract, Add effect dataclasses
    flow.py                 ← Flow, Assert, Emitted dataclasses
    root.py                 ← Spec (top-level aggregate)

  validator/
    engine.py               ← orchestration: load → structural → scenarios → result
    structural.py           ← structural validation (refs, cycles, reachability)
    scenario_runner.py      ← scenario execution: preconditions → effects → postconditions → then
    rule_checker.py         ← evaluate(pred, context) and resolve(operand, context)

  reporter/
    base.py                 ← Finding, ScenarioResult, ValidationResult dataclasses
    terminal.py             ← colored terminal output
    json_reporter.py        ← JSON output

  loader/
    discovery.py            ← discover_files: find all .py files in a directory
    python_loader.py        ← load_module, load_all (returns 3-tuple: specs, modules, errors),
                               collect_from_modules (inspect.getmembers → entities/rules/etc.)

examples/
  ecommerce/                ← single-file example (Order, Wallet, Product, checkout UC)
  taskboard/                ← multi-file example (9 files, 16 scenarios)
tests/
  test_models.py            ← DSL + predicate + structural validation tests
  test_validator.py         ← end-to-end scenario execution tests
  test_loader.py            ← loader tests
  fixtures/
    simple_spec.py          ← minimal passing spec
    broken_spec.py          ← spec with intentional errors (phantom entity)
```

---

## Core concepts

### Entity

Custom metaclass (`EntityMeta`) converts annotated fields to `FieldDescriptor` objects at class creation time. Class-level access returns the descriptor (for predicates); instance-level access returns the stored value.

```python
class Order(Entity):
    status: OrderStatus = OrderStatus.PENDING  # default
    total: float                               # required

Order.total      # → FieldDescriptor (used in predicate expressions)
Order(total=50.0, status=OrderStatus.PENDING).total  # → 50.0
```

`Actor` and `Event` follow the same pattern. `Event` reuses `EntityMeta` via `_init_fields` from `entity.py`.

### Predicate expressions

`FieldDescriptor` overloads comparison operators to return `@dataclass` predicate objects:

```python
Wallet.balance >= Order.total   # → _Gte(left=FieldDescriptor, right=FieldDescriptor)
Product.stock > 0               # → _Gt(left=FieldDescriptor, right=0)
Order.status == OrderStatus.PAID  # → _Eq(left=FieldDescriptor, right=OrderStatus.PAID)
```

Imports inside operator methods are deferred to avoid a circular import between `entity.py` and `predicate.py`.

Logical combinators are factory functions (Python keywords can't be overloaded):
```python
And(pred_a, pred_b)   # → _And(exprs=[pred_a, pred_b])
Or(pred_a, pred_b)    # → _Or(exprs=[...])
Not(pred_a)           # → _Not(expr=pred_a)
```

### Evaluation model

```python
context = {type(inst): inst for inst in scenario.given}  # {Order: order_instance, ...}

resolve(operand, context):
    FieldDescriptor → context[desc.entity_cls].<field_name>
    literal         → as-is

evaluate(_Gte(a, b), context):
    resolve(a, context) >= resolve(b, context)
```

### Scenario execution order

1. Build `context = {type(inst): inst for inst in given}`
2. Evaluate **INVARIANT** and **PRECONDITION** rules against `context`
3. If no precondition errors: apply `UseCase.effects` → `post_context` (shallow copies)
4. Evaluate **POSTCONDITION** rules against `post_context`
5. Evaluate `then=[Assert(pred), Emitted(EventCls)]` against `post_context`
6. If `expected == Expect.FAIL`: invert pass/fail

### Auto-populate Spec

If `Spec(...)` is found with empty lists (the default), `engine._auto_populate()` fills them from all loaded modules via `inspect.getmembers`:
- `Entity` / `Actor` / `Event` subclasses (excluding the base classes themselves)
- `BusinessRule` / `UseCase` / `Scenario` / `StateMachine` / `Flow` instances

Rule: if a list is explicitly non-empty in `Spec(...)` → used as-is. If empty (default) → auto-discover from all modules in the directory.

Deduplication: classes via `set()` (identity), instances via `obj not in seen_list` (list, because pydantic instances are unhashable).

This means a minimal `spec.py` is just:
```python
spec = Spec(id="myproject", name="My Project")
```
…and the loader discovers everything else from the other `.py` files in the same directory.

---

## Key design decisions

- **No pydantic for predicates or effects** — they are `@dataclass`, accessed only via `isinstance()` and attribute reads, never serialized. Pydantic is used only for `BusinessRule`, `UseCase`, `Scenario`, `Spec` (internal models that benefit from validation and future JSON export).
- **No pydantic for Entity** — custom `EntityMeta` metaclass avoids metaclass conflict with pydantic and keeps Entity lightweight.
- **Circular import solved by deferred imports** — `FieldDescriptor.__ge__` etc. import from `predicate.py` inside the method body, not at module level.
- **`_init_fields` shared helper** — both `Entity.__init__` and `Event.__init__` delegate to `_init_fields(instance, kwargs)` in `entity.py`.
- **Effects produce shallow copies** — `_apply_effects` uses `copy.copy(inst)` so the original `given` list is never mutated.
- **`Expect.FAIL` means the scenario documents a blocked path** — it passes when at least one rule rejects the data. The linter prints "correctly blocked" to confirm intent.
- **`Transition(from, to_states)` — no `via`** — StateMachine and UseCase are decoupled. `to_states` can be a single value or a list; `__post_init__` normalizes to list. Effects on UseCase (`Set(field, value)`) are the source of truth for what changes, not SM transitions.
- **`sys.path.insert(0, cwd)`** in `load_module` — required for multi-file examples that use package imports (e.g. `from examples.taskboard.entities import ...`).

---

## Validation rules summary

### Structural (`structural.py`)
- Duplicate ids in rules, use cases, scenarios, state machines, flows
- `FieldDescriptor` refs → entity registered in `spec.entities`, field exists on class
- `UseCase.actor` subclasses `Actor`, registered in `spec.actors`
- `UseCase.requires` → registered use cases, no circular dependencies (DFS)
- `UseCase.emits` / `triggered_by` → registered in `spec.events`
- Emitted events handled by at least one `triggered_by` (WARNING if not)
- `StateMachine.entity_cls` registered in `spec.entities`
- Scenario `given` covers entity types needed by rules (WARNING if missing)
- Scenario `given` state reachable from state machine initial (WARNING if not)
- `Flow` steps registered; `requires` order respected by step order
- `UseCase.effects` target registered entities

### Scenario runner (`scenario_runner.py`)
- INVARIANT / PRECONDITION evaluated against pre-state
- Effects applied only when all preconditions pass
- POSTCONDITION / `then` evaluated against post-state

---

## Commands

```bash
uv run pytest                          # run all tests
uv run pytest tests/test_models.py -v  # specific file
uv run analint examples/ecommerce/    # run linter on example
uv run analint examples/taskboard/    # run multi-file example (16 scenarios)
uv run analint . --format json         # JSON output
```

---

## What NOT to do

- Do not add pydantic to `Entity`, `Actor`, `Event` — metaclass conflict
- Do not import `predicate.py` at the top of `entity.py` — circular import
- Do not mutate `scenario.given` instances — effects work on copies
- Do not add a `kind` field or discriminated union to predicates — dead code, not used anywhere
- Do not add `via=` to `Transition` — it was removed; SM and UseCase are intentionally decoupled
- Do not add `when=` or `Run` to `Scenario` — `when` was removed; `use_case` field is the action
- Do not create `.md` documentation files unless explicitly asked
- Do not add error handling for scenarios that can't happen (e.g. validate that a literal is not None before comparing — the Python operator will raise naturally)
