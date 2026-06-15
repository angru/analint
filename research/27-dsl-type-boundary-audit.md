# DSL type-boundary audit (P4.0a)

**Date:** 2026-06-15

This is the P4.0a audit and design gate (research/26): make the DSL's dual view —
domain-valued *instance* access vs symbolic *class-level* access — explicit, and
decide how much of it static tooling should expose. It is **not** a mandate to
eliminate every `Any` or to change declaration syntax. The approved decision
stands: keep annotation-first declarations (`balance: int`); do not expose
`FieldDescriptor` to authors. Runtime structural validation stays fail-closed —
static typing here is advisory and can be bypassed.

## 1. The dual view

`EntityMeta` replaces class attributes with symbolic field descriptors at runtime,
so the same name means two different things by access path:

| Surface | Author-facing meaning | Runtime role | Honest static role |
|---|---|---|---|
| `wallet.balance` | the balance value | domain value `T` | `T` (correct today) |
| `Wallet.balance` | a reference to an int-valued field | field-reference object | the checker still sees the annotation `int` |
| scoped class field | reference to one slot's field | field-reference object | same as above |
| `Param` / `BoundField` | finite symbolic value/reference | symbolic operand | generic symbolic operand |
| arithmetic expr (`a.x - n`) | derived domain value | AST node | `ValueExpr[T]` (not modelled) |
| `Wallet.balance == 0` | a domain rule | `Predicate` AST node | the checker infers `bool` |
| effect target/value | a field-update relation | writable ref + compatible value | `T` where practical |
| evaluation context | internal state snapshot | heterogeneous `dict` | internal alias, never public JSON |

Instance access is honestly typed and domain-readable; class access is the
embedded DSL's symbolic view. The friction is entirely on the class-access side.

## 2. Reproducing the diagnostics

`[tool.ty.src] include = ["src"]` means CI `ty` checks the library only — the real
authoring surface (the example specs) is invisible. Checked directly, spec files
do produce diagnostics:

| File | `ty` diagnostics |
|---|---:|
| `examples/oauth/assurance.py` | 0 |
| `examples/coin/spec.py` | 3 |
| `examples/ecommerce/spec.py` | 9 |
| `examples/oauth/protocol.py` | 18 |
| `examples/sunless_crypt/spec.py` | 55 |

All of them reduce to **two independent mechanisms**, not many bugs:

1. **Metaclass opacity → `invalid-argument-type` ("Expected `Predicate`, found
   `bool`").** ty reads the source annotation on class access, so
   `Wallet.balance == 50` is inferred `bool` and `Order.status` is inferred
   `OrderStatus`, although `EntityMeta` returns a symbolic descriptor whose
   `__eq__`/`__ge__` build a `Predicate`. 81 of the sampled diagnostics are this.
2. **Mutable-collection invariance → `invalid-assignment`.** `list[Set | Subtract]`
   is not assignable to `list[Effect]`, and a list of concrete predicate node types
   is not assignable to `list[Predicate]`, even when each element is a valid
   subtype. 4 of the sampled diagnostics are this. This is an *input-typing*
   problem, not evidence that the effect/predicate inheritance is wrong.

assurance.py is clean because it uses named predicate objects and quantifier
helpers rather than bare class-level comparisons — a hint that mechanism 1 is the
dominant author-facing cost.

## 3. Export inventory (`analint.__all__`, 48 symbols)

Classified against an *intended minimal DSL*, not assumed correct because exported:

- **Core authoring primitives** — `Entity`, `Field`, `Actor`, `Event`, `Action`,
  `Lifecycle`, `Transition`, `Invariant`, `Spec`, `Scenario`, `Assert`, `Expect`,
  `Flow`.
- **Advanced authoring** — `Scope`, `Bound`, `Param`, `Initial`, `Contract`,
  `Emitted`, `Absent`.
- **Predicate / expression / effect AST** — `Predicate`, `And`, `Or`, `Not`,
  `Implies`, `In`, `IsNull`, `IsNotNull`, `ForAll`, `Exists`, `Count`, `Sum`,
  `Min`, `Max`, `Present`, `Effect`, `Set`, `Subtract`, `Add`, `Create`, `Delete`.
- **Verification queries** — `Reachable`, `Unreachable`, `AlwaysHolds`,
  `NoDeadEnd`, `DeadActions`.
- **Metadata** — `__version__`.
- **Result / reporting types** — none are exported (good: results stay internal).
- **Compatibility aliases** — none remain (the v0.9 deprecations were dropped).

Boundary calls for a future review (not changed here): `InstanceRef` and `Absent`
are advanced surface that authors mostly reach through `Scope`/`Present`; `Effect`
and `Predicate` are AST *bases* exported mainly for typing, not for direct
construction. None should expose `FieldDescriptor`.

## 4. `Any` / suppression inventory

| Kind | Count | Category |
|---|---:|---|
| `type: ignore[override]` (src) | 12 | embedded-DSL protocol conflict — `__eq__`/`__ne__` return `Predicate`, not `bool` |
| `type: ignore[attr-defined]` (src) | 9 | missing closed AST union/protocol — `.left`/`.right` on `Expr` nodes |
| `Any` annotations (src) | 240 | mix: dynamic loader/context boundary, predicate operands, broad public containers |
| `noqa: E712` (examples) | 89 | embedded-DSL idiom — `== True` / `== False` must stay literal to build a `Predicate` |
| `noqa: F401` (examples) | 2 | entry-point re-export (`from . import ...`) |
| ruff `ignore = ANN401` | global | `Any` is part of the public DSL + loader boundary |
| ty `invalid-method-override = ignore` | global | the intentional `__eq__ → Predicate` override |

The two global suppressions are doing a lot of work and are too broad to localise
the real boundaries — that is the main thing P4.0b should tighten.

## 5. Design options (per issue), with costs

- **`attr-defined` on `Expr.left/right` (9).** Replace with a closed expression
  protocol/base carrying typed `left: ValueExpr`/`right: ValueExpr`, or explicit
  `match` on concrete nodes. *Recommend* the closed base (one definition, removes
  all 9, keeps runtime shape). Cost: a small base-class refactor in `models/expr`.
- **`override` on `__eq__` returning `Predicate` (12 + the global ty rule).**
  Localise: keep the override only on the descriptor/ref/expr classes that need it
  and drop the project-wide `invalid-method-override = ignore`. Cost: per-class
  `# ty: ignore[invalid-method-override]` on ~3 classes; net safer (normal classes
  regain override checking).
- **Collection invariance (`invalid-assignment`, 4).** Accept read-only covariant
  inputs (`Sequence[Effect]`, `Sequence[Predicate]`) in public constructors while
  normalising to `list` and preserving Pydantic serialization. Cost: constructor
  signature changes only; no author-visible change.
- **89 `noqa: E712`.** Do **not** weaken E712 globally. Options: (a) a file-level
  `# ruff: noqa: E712` header in spec files (documented spec-file lint policy), or
  (b) a typed predicate helper (`eq(field, True)`) — rejected, it harms domain
  readability. *Recommend* (a): one documented header per spec instead of 89
  inline comments.
- **Metaclass opacity (81, the big one).** No low-maintenance fix preserves
  `balance: int` AND teaches the checker that `Wallet.balance == 0` is a
  `Predicate`: it needs a checker plugin or generated stubs that duplicate model
  semantics. *Recommend* documenting a **narrow inspection policy for spec files**
  (below) and excluding spec files from the *blocking* type gate, rather than
  changing syntax or exposing descriptors. A stub/plugin prototype stays deferred
  unless it can preserve the syntax without duplicating semantics.

## 6. Inspection policy for spec files (proposed)

- The **library** (`src`) stays under the strict, blocking `ty` gate (today's
  config). Spec files (`examples/**`, user specs) are **not** under a blocking
  type gate — their class-level DSL diagnostics are an accepted, documented
  boundary, not a regression signal.
- For editors: document a per-file Pylance/Pyright setting (e.g.
  `# pyright: reportGeneralTypeIssues=false` at the top of a spec, or a workspace
  `python.analysis` override scoped to spec dirs) and the equivalent PyCharm
  inspection scope — so authors get type help on *instance* access and prose
  without red squiggles on every class-level rule.
- A CLI-runnable checker close to the editor experience must back any future
  regression test; `ty` alone is insufficient because Pylance/Pyright is a
  supported authoring surface. (Selection of that checker is a P4.0b task.)

## 7. Decisions / acceptance

- Annotation-first declarations (`balance: int`) are preserved; descriptor-first
  syntax and a parallel `Wallet.fields.balance` namespace are rejected.
- `FieldDescriptor` is never exposed as domain data.
- The class-level "Predicate vs bool" diagnostic is an **accepted checker
  boundary**, documented, not suppressed project-wide.
- Concrete, low-risk fixes that do *not* touch syntax are approved for P4.0b: the
  closed expression base (removes 9 `attr-defined`), localised `__eq__` overrides
  (removes the global ty rule), covariant constructor inputs (removes the 4
  `invalid-assignment`), and a file-level spec lint header (removes 89 inline
  `noqa`).
- Runtime structural validation remains fail-closed regardless of static typing.

The type probes that reproduce these diagnostics as a regression signal live in
`tests/typecheck_probes/` and `tests/test_typecheck_probes.py`.
