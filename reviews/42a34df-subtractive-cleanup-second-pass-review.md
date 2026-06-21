# Review: subtractive cleanup — second-pass (other agent's review + remaining removals)

Reviewed range: `f45edac..42a34df` (the agent's review of `7bcabc4..f45edac`,
its hardening, and the last three removals).

## Verdict

**Approve.** The review of the first three removals was accurate and caught two
real P1 defects the first pass missed; the fixes are correct; the three remaining
removals are done well and honour the locked decisions (research/30 + the
2026-06-20 decision note in ROADMAP block C). One optional nitpick is now fixed.

## The review of the first pass was correct — it found two genuine P1s I missed

1. **`extra="ignore"` left removed fields silently accepted.** After deleting
   `on`/`requires`/`by`/`actors`, the pydantic models (`Action`/`Spec`/`Contract`)
   kept the default `extra="ignore"`, so `Action(on=…, by=…)` still loaded and
   silently discarded them — the removal was *not* fail-closed. This is exactly
   the class of false-green this project cares about, and the first pass missed it.
   Fix (`extra="forbid"`) is correct; verified `Action(on=…)` now raises.
2. **`Flow.given` semantics + crash.** `given=[]` is an empty *partial snapshot*
   (all unscoped entities absent), not "use entity defaults" as the first pass
   documented; `Flow(given=None)` was also constructible and crashed structural
   validation. Fix (required `given`, `__post_init__` rejects `None`, corrected
   docstring, regression tests) is correct.
3. **P2 doc drift** (CHANGELOG `Actor`, example-README `on=` warnings, ROADMAP
   history) — real, and synchronised.

## The three remaining removals are correct and match the locked decisions

- **Raw `Scenario.then` predicates / `Assert`** — `then: list[Predicate | Emitted]`;
  `Assert` is rejected there with a "then" error and *kept* for `Flow.steps`
  (the 2026-06-20 decision). ✓ Regression tests present.
- **Boolean normalization** — `normalize_predicate` is wired into every predicate
  position (invariants, `And/Or/Not/Implies`, quantifiers, `Initial.where`,
  `Scenario.then`, `Action.pre/post`, `Assert`, all queries). A non-boolean bare
  field in a predicate slot is a `ValidationError` (research/30 §5.3 honoured), not
  silently accepted. The E712 spec-wide exception is gone. The snapshot delta is
  benign: only `findings_hash` values changed (predicate rendering); statuses,
  verdicts, state counts and exploration hashes are identical.
- **Lifecycle transition mapping** — `transitions={s: [t, …]}`; the public
  `Transition` wrapper is retired (a test asserts `not hasattr(analint,
  "Transition")`); `terminal` stays an explicit field (not inferred from missing
  keys); the kernel terminal-lock logic was **not** touched (terminal narrowing
  was deliberately deferred).

## Nitpick (fixed in this pass)

`Scenario` is a pydantic `BaseModel` and still had the default `extra` — a typo'd
or stale field would be silently ignored. Added `extra="forbid"` and a regression
test. (`Reachable`/`Unreachable`/`AlwaysHolds`/`NoDeadEnd`/`DeadActions`,
`Invariant`, `Lifecycle`, `Initial` are dataclasses and already reject unknown
keywords — no change needed.)

## Checks run

```text
uv run pytest -q            → 355 passed, 1 skipped
uv run ruff check .         → passed
uv run ty check             → passed
analint check examples/*    → all PASS (characterization snapshot green)
git diff f45edac..42a34df -- tests/snapshots/examples.json
                            → only findings_hash changes (predicate rendering)
```

## Conclusion

The subtractive core is complete and sound: the four false affordances
(`on`/`requires`/`Actor`/`by`) are gone and fail-closed on reuse, checkpoints and
lifecycle tables use the honest native forms, and boolean predicates read
naturally. The contract is ready to document (ROADMAP block B / MkDocs). Deferred
by design: `Key(...)` scope-key value + explicit scope presence (additive, 0.0.2),
and lifecycle `terminal` narrowing (no evidence yet).
