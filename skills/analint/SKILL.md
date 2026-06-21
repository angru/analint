---
name: analint
description: Model, inspect, validate, and safely modify executable system specifications built with the analint Python DSL. Use when a repository contains an analint `spec.py`, imports from `analint`, or the user asks to describe entities, invariants, actions, lifecycles, scenarios, flows, reachability, impact analysis, counterexample traces, or verified business/game rules with analint.
---

# analint

Use analint's CLI as the source of truth. Do not infer whether a specification is
valid from reading Python alone.

This skill targets analint `0.0.1+` and the versioned `v1` JSON schemas.

## Start by orienting

1. Run `analint --version`. If unavailable, report that `analint` must be
   installed; do not recreate its validator in ad-hoc code.
2. Locate the entry point: a `spec.py` file or an explicitly supplied Python
   file.
3. Inspect the model before scanning or editing source:

```bash
analint show -p PATH
analint show action ACTION_ID -p PATH
analint show entity ENTITY_NAME -p PATH
```

`show` returns JSON. Use its ids and names instead of guessing them.

## Follow the change workflow

For every behavior change:

1. Inspect the relevant object with `show`.
2. Assess the blast radius before editing:

```bash
analint affects Entity.field -p PATH
analint affects ACTION_ID -p PATH
```

3. For an additive hypothesis, create a standalone Python file and validate it
   without changing the specification:

```bash
analint check PATH --what-if /tmp/hypothesis.py --format json
```

The hypothesis may add invariants, actions, scenarios, or queries. Import the
loaded entry module through `analint_spec` when the file needs existing model
objects:

```python
from analint import Invariant
from analint_spec import Order

positive_total = Invariant(Order.total > 0, label="Order total is positive")
```

4. Apply the smallest source change after the result matches the intended
   behavior.
5. Validate the actual specification:

```bash
analint check PATH --format json
```

6. Inspect reachability only when the task concerns possible states, dead ends,
   dead actions, or action order:

```bash
analint explore PATH --query QUERY_ID --format json
analint trace QUERY_ID -p PATH --format json
```

Use terminal output for humans and JSON for decisions or automation.

## Interpret results fail-closed

- Exit `0`: effective `PASS`.
- Exit `1`: findings or failed checks.
- Exit `2`: invalid command usage.
- Exit `3`: specification load failure.
- Exit `4`: `INCONCLUSIVE`; the exploration budget proved nothing.

Never describe `INCONCLUSIVE` or `NOT_CHECKED` as success. Report excluded
actions, vacuous predicates, capped exploration, and evaluation errors when
present. Machine-facing results identify their contract through `schema`, such
as `analint.check/v1`, `analint.show/v1`, or `analint.exploration/v1`.

`NoDeadEnd(goal)` proves recoverability: a goal remains reachable from every
reachable state. It does not prove eventual completion or liveness.

## Preserve analint semantics

- Treat effects as simultaneous facts. Resolve every right-hand side against the
  pre-state; never make one effect observe another effect from the same action.
- Put one-field domains and ranges in `Field(...)`, relational world rules in
  `Invariant(...)`, and state transitions in inline `Lifecycle(...)`.
- Treat terminal lifecycle state as freezing the whole entity against effects.
- Use plain predicates in `pre`, `post`, and assertions. Do not introduce removed
  wrappers such as `Transition`, `BusinessRule`, `UseCase`, `StateMachine`,
  `via=`, or scenario `when=`/`Run`.
- Use `Param` and `params=` for action families. Do not generate model elements
  with host-language factory functions.
- Use `Scope` for bounded multiplicity. Class-level fields of scoped entities are
  ambiguous; use instance references, bound fields, or params.
- Treat absent scoped slots as unreadable and unmodifiable. Use `Present`,
  `Create`, `Delete`, and `Absent` explicitly.
- Keep effects from conflicting: one field target once per action; do not combine
  `Create`/`Delete` with field updates on the same slot.
- Use only one query start form: `given`, `given_any`, or `initial`.
- Treat `Expect.FAIL` as a successful pre-execution rejection only. Effect,
  postcondition, assertion, or evaluation defects still fail the scenario.

## Respect loader rules

- Load a specification through one entry point.
- In packaged multi-file specifications, use relative imports.
- Ensure every model file is reachable from the entry point.
- Use one root `Spec`; compose reusable public fragments with `Contract`.
- Let module-level variable names supply optional ids. When constructing DSL
  objects directly outside the loader, pass explicit ids where required.
- Never compare collected DSL objects with `==`; overloaded predicate operators
  make equality semantic. Use object identity.

## Finish with evidence

Summarize:

- what model behavior changed;
- which `show`/`affects` evidence guided the edit;
- the final `check` verdict;
- relevant query completeness and trace;
- any remaining `INCONCLUSIVE`, excluded, or unassessed behavior.

When changing analint itself, do not regenerate characterization snapshots
mechanically. Review every graph or verdict delta first.

## Go deeper

For the full DSL reference and worked example specs (these links are absolute, so
they work without cloning the repository):

- Documentation and DSL reference: <https://angru.github.io/analint/>
- Canonical example specs to study patterns from:
  <https://github.com/angru/analint/tree/main/examples>

`analint show -p PATH` on any existing spec is the fastest way to learn its
shape; prefer it over reading source.
