#!/usr/bin/env python
"""Count a spec's reachable canonical states with little memory.

The same transitions as ``explore()`` — kernel ``step``, ``state_key``,
invariant-violating states kept but not expanded — but only state keys are
retained (no contexts, parents or edges). For cross-checking a state count
against TLC on models too large for an in-memory exploration
(research/34 §8 B2). Not a verifier: it reports no findings.

    uv run python scripts/count_states.py benchmarks/broker/m6_risk.py
"""

from __future__ import annotations

import resource
import sys
import time
from collections import deque
from pathlib import Path

from analint.validator.engine import build_spec
from analint.validator.explorer import build_canonical_initials, state_key
from analint.validator.kernel import Outcome, step
from analint.validator.state_checks import invariant_holds, invariant_is_applicable


def count_states(path: Path) -> dict:
    spec, _, errors = build_spec(path)
    if spec is None or errors:
        raise SystemExit(f"cannot load {path}: {errors}")
    initials, error = build_canonical_initials(spec)
    if not initials:
        raise SystemExit(f"no canonical initial state: {error}")

    def legal(ctx: dict) -> bool:
        return not any(
            invariant_is_applicable(inv, ctx) and not invariant_holds(inv, ctx)
            for inv in spec.invariants
        )

    seen: set = set()
    queue: deque = deque()
    defects = illegal = 0

    def visit(ctx: dict) -> None:
        nonlocal illegal
        key = state_key(ctx)
        if key in seen:
            return
        seen.add(key)
        if legal(ctx):
            queue.append(ctx)
        else:
            illegal += 1

    for ctx in initials:
        visit(ctx)
    while queue:
        ctx = queue.popleft()
        for action in spec.actions:
            result = step(spec, action, ctx, explain=False)
            if result.outcome is Outcome.DEFECT:
                defects += 1
            elif result.outcome is not Outcome.REJECTED and action.effect:
                visit(result.post_context)
    return {"states": len(seen), "defects": defects, "illegal": illegal}


if __name__ == "__main__":
    started = time.perf_counter()
    counts = count_states(Path(sys.argv[1]))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # bytes on macOS
    print(counts, f"{time.perf_counter() - started:.0f} s, peak RSS ~{rss:.0f} MiB")
