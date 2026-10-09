# 35 — Explicit composition root: the model is what `Spec` references

**Date:** 2026-10-09
**Status:** direction accepted for the roadmap (ROADMAP P5.0); each
implementation step is review-gated
**Revisits:** research/09 (loader), research/30 §4.5 (`Contract`/`Spec`
marked "stable, no change")

## 1. Question

In practice the root `Spec(...)` feels like it "floats". Nothing is passed
into it, yet it is required. Multi-file specs import modules only so that
analint can see them. And it is unclear whether analint parses Python files
itself. Should the model instead be registered explicitly in `Spec`, so that
every import has a purpose?

## 2. What the code does today

**Loading uses the standard import system; there is no custom parser.**
`loader/python_loader.py` imports the entry point once (`importlib`; a
standalone `spec.py` is executed like `python spec.py`), and Python resolves
the rest of the import graph. `loader/discovery.py` only lists `.py` files
for the "file not imported from the entry point" warning. The earlier
file-walking loader, with its double-import bug, was removed after
research/09.

**Membership is decided by scanning module globals.** After the import,
`collect_from_modules` runs `inspect.getmembers` over every loaded module
under the entry's directory. It collects every bound `Entity`/`Event`
subclass and every `Action`/`Invariant`/`Scenario`/`Flow`/`Scope`/
`Lifecycle`/query instance, and fills empty ids from variable names.
`engine._auto_populate` then copies the collected objects into the `Spec`.
research/09 had recommended a registry; the scan was implemented instead.

**An explicit mode already exists.** `Contract` + `Spec(imports=[...])`
switches auto-population off and uses only the listed objects. The scan
still runs, but only to fill ids. research/30 §4.5 calls explicit `Contract`
lists "intentional ceremony" because auto-discovery "would reintroduce the
composition leak". The root `Spec` is the one place where that leak remains
the default.

Observed consequences:

| Symptom | Where |
|---|---|
| `Spec` carries only metadata in 10 of 11 examples (only OAuth composes explicitly) | `examples/*/spec.py` |
| Side-effect imports whose only job is to make modules visible to the scanner | `examples/taskboard/spec.py`: `from . import flows, scenarios  # noqa: F401` |
| Membership = "any DSL object bound to a global in a spec module". A helper or experimental `Action` left in a module silently becomes behaviour | `collect_from_modules` |
| Per-field mixed mode: listing `actions=[...]` explicitly still auto-collects invariants, scenarios, … for every list left empty | `_auto_populate._resolve` |
| Action order (therefore BFS order and which witness is found first) is alphabetical by module and variable name, not the author's order | `sorted(closure)` + `inspect.getmembers` |

## 3. Why change it now

- **Large models.** The private spec behind issue #3 and the planned broker
  benchmark (research/34) have many processes. A reviewer must be able to
  see what is in the model, and the natural unit for grouping, reporting and
  scenarios is one `Contract` per process.
- **Honesty.** Silent inclusion of an unintended action adds behaviour no one
  reviewed. Explicit registration introduces the opposite risk, silent
  *omission*: a forgotten action means less behaviour, which can make an
  invariant pass that should fail. The design therefore pairs explicitness
  with a loud orphan warning (R4). Omission becomes visible instead of
  trading one silent failure for another.
- **Meaningful imports.** Every import in a spec should be there because its
  object is referenced, as in ordinary Python code.

## 4. Options

| Option | Membership defined by | Verdict |
|---|---|---|
| A. Status quo + documentation | module globals | rejected: the confusion is the design, not missing docs |
| B. Global registry on construction (research/09 option C, Django-style) | "constructed during load" | rejected: still implicit, and global state leaks across tests, REPL and long-running MCP processes |
| **C. Explicit root + reference closure** | what `Spec` and its `Contract`s reference | **proposed** |
| D. Class-based contracts (`class Cards(Contract): create = Action(...)`, ids via `__set_name__`) | class body | deferred: removes the id scan too, but it is a new authoring style and metaclass work with no new semantics |

## 5. Proposal (option C)

- **R1 Membership.** Model = `Spec` local lists ∪ the lists of every imported
  `Contract` ∪ the reference closure (R2). Nothing else.
- **R2 Reference closure.** Entities, events, inline lifecycles and scopes
  are derived from the behaviour objects that reference them: `pre`, effects,
  `post`, `emits`, scenario `given`, `Initial`, quantifier binders and `Param`
  domains (via `InstanceRef.scope`). Listing them explicitly remains allowed.
  Two different `Scope` objects over one entity type are a structural error.
  Behaviour (actions, invariants, scenarios, flows, queries) is never derived;
  it is always listed.
- **R3 Ids.** A naming pass assigns empty ids from module variable names *by
  identity* and only to model members. The scan no longer decides
  membership. A member that is not bound to any module variable needs an
  explicit `id=`; the existing missing-id structural error covers it.
- **R4 Orphan warning.** A behaviour object bound in a spec module but absent
  from the model produces `WARNING loader:<module>.<name> — defined but not
  part of the model`. It is visible in JSON, and `--strict` makes it fail as
  any warning does. The unloaded-file warning stays.
- **R5 No mixed mode.** Empty lists mean empty. A `Spec` with no behaviour at
  all is a structural error ("empty model"), not an invitation to scan.
- **R6 What-if.** The `--what-if` file is itself the explicit registration:
  its top-level DSL objects are merged into the model. It is the only scanned
  module, and the CLI argument names it. Agent workflows do not change.
- **R7 Order.** Model order is declaration order: `imports` order, then list
  order. It is deterministic and controlled by the author.
- **R8 Contracts are not soundness boundaries.** They group a process for
  people and reports. The property slice (research/34 §5) is computed from
  data dependencies and never assumes that two contracts are independent.

### Before / after (taskboard)

```python
# before — spec.py
from analint import Spec
from . import flows, scenarios  # noqa: F401  (imported only for the scanner)

spec = Spec(id="taskboard", name="Task Board (Trello-like)")
```

```python
# after — cards.py
cards = Contract(
    id="cards",
    actions=[create_card, move_card, archive_card, assign_card, add_comment],
    scenarios=[sc_create_card_ok, sc_create_card_archived_board, sc_move_card_ok,
               sc_move_archived_card, sc_assign_ok, sc_assign_nonmember],
)

# after — spec.py
from analint import Spec

from .cards import cards
from .membership import membership

spec = Spec(id="taskboard", name="Task Board (Trello-like)", imports=[cards, membership])
```

Entities (`Board`, `Card`, …), events and lifecycles are no longer listed;
they follow from the actions that use them (R2).

## 6. Relation to research/34

- The broker benchmark (P5 B1) is written in this style from the start, with
  one `Contract` per process (KYC, trading accounts, payments, partners). It
  also tests the ergonomics of explicit composition on a realistic model.
- Per-contract reporting, or `check --contract kyc` for the scenarios, flows
  and queries a contract owns, is a natural later addition, but is not part
  of this phase.
- Slicing (P5 C) does not depend on this work, and by R8 it must not.

## 7. Migration and gates

Scope: about 267 top-level behaviour objects across the 10 auto-populated
examples (counted as module-level `Action`/`Invariant`/`Scenario`/`Flow`/
query assignments; OAuth is already explicit). This is a breaking change for
0.0.2, without deprecation aliases, following the research/30 precedent for
pre-1.0 cleanups.

**Characterization gate.** Verdicts, findings, state and edge counts and
graph hashes must stay identical. Witness traces may change only where R7
changed the action order: BFS returns the first witness it finds, so an
equally short trace can pick different actions. Each trace delta is reviewed
and explained, never regenerated mechanically (`tests/snapshots/README.md`).

**Fail-closed probes** (each must surface, not merely agree):

1. A stray `Action` in an imported helper module is **not** in the model
   **and** is reported as an orphan.
2. A scenario that references an unregistered action is a structural error
   (`action '…' not in spec.actions` exists today; keep it).
3. An entity referenced only by a scenario's `given` is derived.
4. Two `Scope`s over one entity type are a structural error.
5. An invariant added through `--what-if` is merged and can turn the verdict
   to `FAIL`.
6. Removing an action from a contract changes the explored graph; no scan
   re-adds it.

## 8. Plan (one reviewable commit each)

1. **Naming pass + orphan warning (R3, R4)**, behaviour-neutral: in auto
   mode nothing is orphaned yet. Probe 1 is written here against the
   explicit mode.
2. **Reference closure (R2)**, additive: `Contract`/`Spec` lists for
   entities, events, scopes and lifecycles become optional. Probes 3 and 4.
3. **Migrate the examples** one by one to explicit roots while auto mode
   still exists, so each migration passes the characterization gate on its
   own.
4. **Remove auto-population (R1, R5, R7)**: delete `_auto_populate`'s scan
   path, the mixed per-field mode and the membership use of
   `collect_from_modules`; keep R6. Probes 2, 5 and 6.
5. **Documentation:** AGENTS.md (Loader, Auto-populate), README, docs site,
   the agent skill, CHANGELOG (breaking change).

Steps 1–3 are non-breaking; step 4 is the break.

## 9. Open questions

1. Derive entities, events and scopes (R2, proposed), or keep the research/30
   ceremony of listing them? Recommendation: derive. Listing remains possible
   in a `Contract` that wants to document its exports.
2. Should the orphan warning be an error by default rather than only under
   `--strict`? Recommendation: a warning by default, like the unloaded-file
   warning, so that work-in-progress modules do not block checks.
3. Option D (class-based contracts) would remove the id scan entirely.
   Revisit only if the naming pass causes real problems.
