#!/usr/bin/env python
"""Scaling characterization over generated model families (P4.4).

Informational, NOT a CI gate: timing/memory are hardware- and runtime-dependent.
It drives engine work with reproducible state spaces (scaling_models.py) and
verifies the closed-form state counts so the families stay correct.

    uv run python scripts/bench_scaling.py            # human-readable table
    uv run python scripts/bench_scaling.py --json     # machine-readable
    uv run python scripts/bench_scaling.py --full     # include the ~10^5 tier (slow)

Per case: reachable states/edges/actions/roots/completeness, explore wall time
(median + min over repetitions), peak memory, time/state, bytes/state, and the
artifact-summary build overhead as a fraction of exploration time.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scaling_models import conserved_transfer, counter_grid, workflow_product

from analint.validator.artifact_builder import build_exploration_artifact
from analint.validator.explorer import build_canonical_initials, explore

# (family, args, tier) where tier is the target decade of reachable states.
CASES = [
    ("counter_grid", (2, 9), 2),
    ("counter_grid", (3, 9), 3),
    ("counter_grid", (4, 9), 4),
    ("counter_grid", (5, 9), 5),
    ("conserved_transfer", (4, 7), 2),
    ("conserved_transfer", (4, 16), 3),
    ("conserved_transfer", (5, 20), 4),
    ("conserved_transfer", (6, 24), 5),
    ("workflow_product", (4,), 2),
    ("workflow_product", (5,), 3),
    ("workflow_product", (7,), 4),
    ("workflow_product", (8,), 5),
]
_BUILDERS = {
    "counter_grid": counter_grid,
    "conserved_transfer": conserved_transfer,
    "workflow_product": workflow_product,
}


def _measure(family: str, args: tuple) -> dict:
    spec, expected = _BUILDERS[family](*args)
    initials, error = build_canonical_initials(spec)
    if initials is None:
        raise SystemExit(f"{family}{args}: cannot build initial: {error}")

    big = expected > 20_000
    reps = 1 if big else 3
    explore(spec, initials, expected + 10)  # warmup (also primes any caches)

    times: list[float] = []
    for _ in range(reps):
        initials, _ = build_canonical_initials(spec)
        start = time.perf_counter()
        exp = explore(spec, initials, expected + 10)
        times.append(time.perf_counter() - start)

    tracemalloc.start()
    initials, _ = build_canonical_initials(spec)
    exp = explore(spec, initials, expected + 10)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    art_start = time.perf_counter()
    artifact = build_exploration_artifact(exp, spec)
    art_time = time.perf_counter() - art_start

    states = len(exp.states)
    t_min, t_med = min(times), statistics.median(times)
    return {
        "family": family,
        "args": list(args),
        "expected_states": expected,
        "states": states,
        "edges": len(exp.edges),
        "actions": len(spec.actions),
        "roots": len(exp.roots),
        "complete": not exp.capped,
        "counts_match": states == expected,
        "explore_time_min_s": round(t_min, 6),
        "explore_time_median_s": round(t_med, 6),
        "peak_memory_bytes": peak,
        "time_per_state_us": round(t_min / states * 1e6, 3),
        "bytes_per_state": round(peak / states, 1),
        "artifact_time_s": round(art_time, 6),
        "artifact_overhead_pct": round(art_time / t_min * 100, 1) if t_min else 0.0,
        "artifact_states": artifact.summary["states"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--full", action="store_true", help="include the ~10^5 tier (slow)")
    args = parser.parse_args()

    cases = [c for c in CASES if args.full or c[2] < 5]
    rows = [_measure(family, params) for family, params, _tier in cases]
    meta = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }

    if args.json:
        print(json.dumps({"meta": meta, "rows": rows}, indent=2))
        return

    print(f"# scaling characterization  ({meta['implementation']} {meta['python']})")
    header = (
        f"{'family':<20}{'args':<10}{'states':>8}{'edges':>9}{'t_min(ms)':>11}"
        f"{'us/state':>10}{'B/state':>9}{'art%':>7}{'ok':>4}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['family']:<20}{tuple(r['args'])!s:<10}{r['states']:>8}{r['edges']:>9}"
            f"{r['explore_time_min_s'] * 1000:>11.2f}{r['time_per_state_us']:>10.2f}"
            f"{r['bytes_per_state']:>9.0f}{r['artifact_overhead_pct']:>7.1f}"
            f"{('OK' if r['counts_match'] else 'BAD'):>4}"
        )


if __name__ == "__main__":
    main()
