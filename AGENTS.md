# AGENTS.md — analint

Context for AI agents working in this repository.

## What this project is

analint is a **Python DSL for declaring and verifying system behaviour**: domain entities, constraints, actions (state transitions), lifecycles, and scenarios — checked by a linter/validator. The domain is intentionally generic: business analytics, game rules, and narrative consistency all use the same primitives (see `examples/`).

The central idea: constraints are predicate expressions over entity fields (`Wallet.balance >= Order.total`), actions declare pre/effect/post, scenarios provide concrete instances, and the validator evaluates everything against that data.

`research/` holds the design research (universal DSL, declarative semantics, reachability roadmap, AI-agent use case). `ROADMAP.md` holds the plan; current phase is v0.9 (done) → v0.10 (agent-facing CLI).

## Repository layout

```
src/analint/
  __init__.py               ← public API — all user-facing symbols exported here
  cli.py                    ← typer CLI: check / show / affects (bare PATH → check)
  query.py                  ← read-only model queries (overview, describe, affects)
  mcp_server.py             ← MCP stdio server (optional `mcp` extra)

  models/
    entity.py               ← Entity base, EntityMeta metaclass, FieldDescriptor, _init_fields
    actor.py                ← Actor base class (role markers)
    event.py                ← Event base class (same metaclass as Entity)
    predicate.py            ← _Eq, _Gte, _Implies … dataclasses + And/Or/Not/Implies factories
    invariant.py            ← Invariant dataclass (world-level constraint)
    action.py               ← Action (pre / effect / post / emits / on / requires / by)
    effect.py               ← Set, Subtract, Add effect dataclasses
    lifecycle.py            ← Lifecycle (with terminal states), Transition
    scenario.py             ← Scenario, Expect enum
    flow.py                 ← Flow, Assert, Emitted dataclasses
    root.py                 ← Spec (top-level aggregate)

  validator/
    engine.py               ← orchestration: load → auto-populate → structural → scenarios
    structural.py           ← static validation (refs, cycles, payload bindings, terminal)
    scenario_runner.py      ← invariants → pre → effects (simultaneous) → post → then
    rule_checker.py         ← evaluate(pred, context) and resolve(operand, context)

  reporter/                 ← Finding/ScenarioResult/ValidationResult, terminal + JSON output

  loader/
    discovery.py            ← discover_files (used only for unloaded-file warnings)
    python_loader.py        ← entry-point import, closure cache, collect_from_modules

examples/
  ecommerce/spec.py         ← single-file example
  taskboard/                ← multi-file example (relative imports, 16 scenarios)
  cloak/spec.py             ← Cloak of Darkness — game spec example
tests/                      ← test_models, test_validator, test_loader + fixtures/
```

## Core concepts

### Entity / Event

`EntityMeta` converts annotated fields to `FieldDescriptor` objects at class creation. Class-level access returns the descriptor (for predicates); instance-level access returns the value. `Event` reuses the same metaclass — so event payloads work in predicates exactly like entity fields. `_init_fields` raises on unknown **and** missing required fields.

### Predicates

`FieldDescriptor` overloads comparison operators to return `@dataclass` predicate objects. Combinators: `And/Or/Not/Implies/In/IsNull/IsNotNull`. Predicates are plain values — specs name and reuse them (`board_is_active = Board.status == BoardStatus.ACTIVE`).

Imports inside operator methods are deferred to avoid a circular import between `entity.py` and `predicate.py`.

### Evaluation model

```python
context = {type(inst): inst for inst in scenario.given}   # entities AND events
resolve(FieldDescriptor, context) → getattr(context[desc.entity_cls], desc.field_name)
evaluate(_Gte(a, b), context) → resolve(a) >= resolve(b)
```

### Scenario execution order (scenario_runner.py)

1. World invariants (skipped when `given` lacks the referenced entities) + `action.pre`
2. Terminal guard: entity whose lifecycle field is terminal must not be touched by effects
3. Effects applied **simultaneously**: all right-hand sides resolved against the *pre*-state
4. `action.post` + invariants re-checked against the post-state
5. `then` assertions; `Emitted` accepts both event classes and payload templates in `emits`
6. `Expect.FAIL` inverts pass/fail ("correctly blocked")

### Loader (python_loader.py)

The spec is loaded through a **single entry point** (`spec.py` or an explicit file) via the standard import system:

- packaged specs (with `__init__.py`) are imported under their real qualified name — this prevents the duplicate-class-identity bug; multi-file specs must use **relative imports**
- standalone files are imported under a synthetic unique name (nothing imports the entry itself)
- the import closure is cached per entry path (`_CLOSURE_CACHE`) so repeated loads in one process reuse identities
- `collect_from_modules` walks the loaded modules, collects instances, and **fills empty `id` fields from variable names**
- a `.py` file in the directory not reachable from the entry point → warning (engine.`_unloaded_file_warnings`)

### Auto-populate Spec (engine.py)

`Spec(...)` with empty lists → `_auto_populate` fills them from collected objects. Non-empty list → used as-is. Dedup of instances is **by object identity** (`id(obj)`), never `==` — dataclass equality on predicate fields hits the overloaded operators.

## Key design decisions

- **Effects are facts, not commands** — simultaneous semantics, RHS on pre-state, two effects on one field = structural error. Don't make them sequential. (research/07)
- **No `BusinessRule`/`RuleType` wrappers** — preconditions are plain predicates in `pre=`, world constraints are `Invariant(...)`. Placement *is* the semantics.
- **No pydantic for Entity/Event/predicates/effects/Invariant/Lifecycle** — metaclass conflict / unnecessary; pydantic only for `Action`, `Scenario`, `Spec`.
- **ids are optional** — derived from module-level variable names by the loader. Tests constructing objects directly must pass `id=` explicitly.
- **Terminal lifecycle states block modification** — both statically (no transition out) and at runtime (effects on a terminal entity fail).
- **Event payload templates** — `emits=[CardCreated(card_id=Card.id)]` binds payload to state expressions; structural validation checks fields and annotation compatibility; subscriber `pre` can reference event fields because Event instances can live in `given`.

## Commands

```bash
uv run pytest                          # run all tests (75)
uv run analint examples/ecommerce/    # 4 scenarios  (= analint check …)
uv run analint examples/taskboard/    # 16 scenarios, multi-file
uv run analint examples/cloak/        # 11 scenarios, game spec
uv run analint check . -f json         # machine-readable validation
uv run analint show action create_card -p examples/taskboard/
uv run analint affects Board.card_count -p examples/taskboard/
uv run analint check . --what-if /tmp/hypothesis.py   # hypothesis without editing files
```

Exit codes: 0 ok · 1 findings · 2 usage · 3 spec failed to load.

## Working on a spec as an agent (the intended loop)

1. **Orient** — `analint show -p <spec>` for the model overview; `show action <id>`
   for details. This replaces grepping the spec files.
2. **Assess impact** — before changing a field or action:
   `analint affects Card.status -p <spec>` (who reads/writes it, which invariants
   and lifecycles constrain it, which scenarios cover it).
3. **Test the hypothesis** — write the new invariant/scenario into a standalone
   file and run `analint check <spec> --what-if <file>`; iterate until the
   outcome matches the intent.
4. **Apply** — move the change into the spec files, run `analint check <spec>`,
   fix findings, commit.

The MCP server (`analint-mcp`, optional `mcp` extra, `src/analint/mcp_server.py`)
exposes the same three operations as tools: `check`, `show`, `affects`.
Query logic lives in `src/analint/query.py` — plain dict-returning functions
shared by the CLI and MCP.

## What NOT to do

- Do not reintroduce `via=` on Transition, `when=`/`Run` on Scenario, or `BusinessRule`/`UseCase`/`StateMachine` — removed in v0.9; the migration map lives in `research/05-universal-dsl.md`
- Do not make effects sequential or let one effect observe another — simultaneity is a semantic guarantee with a test (`test_effects_are_simultaneous`)
- Do not compare collected DSL instances with `==` — use object identity (`id(obj)`)
- Do not add pydantic to `Entity`/`Actor`/`Event` — metaclass conflict
- Do not import `predicate.py` at the top of `entity.py` — circular import
- Do not mutate `scenario.given` instances — effects work on copies
- Do not load spec files with `spec_from_file_location` per file — that resurrects the double-import bug; everything goes through the entry point
- Do not create `.md` documentation files unless explicitly asked
- Do not add error handling for scenarios that can't happen — let Python raise naturally
