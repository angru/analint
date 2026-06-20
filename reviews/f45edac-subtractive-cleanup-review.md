# Review: subtractive core cleanup, first three removals

Reviewed range: `7bcabc4..f45edac`

## Verdict

The direction matches research/30. Do not revert the removals, but two P1
issues must be fixed before continuing the cleanup.

## Findings

### P1 — Removed fields are silently ignored

`Action`, `Spec`, and `Contract` retain Pydantic's default `extra="ignore"`.
Declarations using removed fields (`on`, `requires`, `by`, `actors`) therefore
load successfully and silently discard them. Several tests still pass `on=` and
remain green only for this reason.

Set `extra="forbid"` on these public models, migrate the stale tests, and add
regressions for removed and misspelled keywords.

### P1 — `Flow` does not require an initial world

`Flow.given` now defaults to `[]`, but flows use the partial-snapshot builder:
an empty list means every unscoped entity is absent, not that entity defaults
are materialized. A defaulted entity action therefore rejects as not applicable.

Explicit `Flow(given=None)` is also constructible and crashes structural
validation with `TypeError: 'NoneType' object is not iterable`.

Make `given` required, reject `None`, and document that `given=[]` is an empty
partial snapshot. Do not switch Flow to the canonical defaults-built world;
that would break Scenario/Flow snapshot parity.

### P2 — Documentation still describes the deleted API

- `examples/ecommerce/README.md` and `examples/taskboard/README.md` still promise
  `on=` handler warnings that no longer exist.
- `CHANGELOG.md` still lists `Actor`.
- earlier ROADMAP status sections still describe documentary
  `Actor/by/on/requires` and non-executable flows.

Synchronize these before documentation freeze.

## Checks run

```text
uv run pytest -q
342 passed, 1 skipped

uv run ruff check .
passed

uv run ty check
passed

uv run analint examples/ecommerce
PASS, zero warnings

uv run analint examples/taskboard
PASS, one warning

uv run analint examples/fulfillment
PASS

git diff 7bcabc4..f45edac --check
passed
```

## Recommended next step

1. Forbid unknown public-model fields and migrate stale tests.
2. Require and validate `Flow.given`.
3. Synchronize docs and roadmap history.
4. Then continue raw `Scenario.then` predicates, boolean normalization, and
   lifecycle transition mappings.
