# Characterization snapshots

`examples.json` is a **characterization** baseline, not a specification of
correct behaviour. It records what the engine *currently* does for every example
(verdict, per-scenario status/rules/findings, per-query trace/findings and a
deduplicated table of graph hashes, roots, fired/excluded actions and
completeness) so that an
*unintended* behaviour change shows up as a diff.

## Regenerating

```
UPDATE_SNAPSHOT=1 uv run pytest tests/test_characterization.py
```

**Never regenerate mechanically.** A snapshot diff means one of two things, and
they look identical to the tool:

1. a regression — investigate and fix;
2. an *intended* behaviour change — only then regenerate, and the diff must be
   reviewed and explained in the commit message.

A change in `states_hash`/`edges_hash` at a constant state count means the
reachable graph changed shape — treat it as significant, not noise.
`incomplete` records `capped` and `excluded-semantics`; a PASS with a new
incompleteness reason is therefore a visible snapshot change.

## Expected deltas from the transition kernel (research/20 §2, review 584d819)

When `scenario_runner` and `explorer` are unified behind one transition kernel,
these baseline changes are **expected** (anything else in the diff is suspect):

- **Lifecycle transition validation appears in scenarios.** Today only the
  explorer rejects an undeclared lifecycle transition; the scenario runner does
  not. A scenario performing an undeclared transition should flip PASS→FAIL.
- **`Delete` counted by the terminal guard.** Today the terminal guard only
  inspects `Set/Add/Subtract`; a `Delete` of a terminal-state instance is not
  blocked. Affected scenarios/queries may change.
- **Emitted payload fully checked.** Today a scenario's `Emitted` assertion
  reduces to an event-class check; binding/payload mismatches should surface.
- **Effectless `Action.post`** is already no longer bypassed (commit 50db26c) —
  listed for completeness.
- **Unified ordering of checks** (pre-state invariants → pre/terminal/presence
  guards → effects → field constraints → lifecycle → post → post-state
  invariants → emitted payload materialization) across both paths;
  ordering-dependent findings may move.
- **Evaluation errors are model defects.** They are never a normal action
  rejection and `Expect.FAIL` must not legitimise them.
- **Invalid pre-state invariants are model defects.** They do not mean the
  action was correctly blocked.

No example currently exercises the first three divergences (the snapshot was
stable across the effectless-post fix), so the kernel is expected to leave
`examples.json` unchanged. If it does change, that is a signal to add a targeted
example or confirm the delta is one of the above — not to regenerate blindly.

The real gate for the kernel is the semantic conformance matrix
(`tests/test_transition_conformance.py`, research/20 §1), which runs one action
through both paths and asserts they agree; this snapshot is the coarse
example-level net.
