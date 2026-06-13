#!/usr/bin/env python
"""Informational performance snapshot of the example specs.

Prints wall-clock time and reachable-state counts per example. This is NOT a
test and NOT a gate: timing is hardware- and runtime-dependent, so it is for
eyeballing trends (e.g. before/after an engine change), never for asserting.
The behavioural regression oracle is tests/test_characterization.py.

    uv run python scripts/bench.py            # human-readable table
    uv run python scripts/bench.py --json     # machine-readable

Each example is run several times; the fastest run is reported (least noise).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from analint.validator.engine import validate

EXAMPLES = Path(__file__).parent.parent / "examples"
REPEATS = 5


def _measure(path: Path) -> dict:
    best_ms = float("inf")
    result = None
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        result = validate(path)
        best_ms = min(best_ms, (time.perf_counter() - t0) * 1000)
    assert result is not None
    states = max((qr.states_explored for qr in result.query_results), default=0)
    return {
        "verdict": str(result.verdict),
        "states_explored": states,
        "best_ms": round(best_ms, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()

    names = sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir())
    data = {name: _measure(EXAMPLES / name) for name in names}

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"{'example':<14} {'verdict':<13} {'states':>8} {'best ms':>10}")
    print("-" * 48)
    for name, row in data.items():
        print(
            f"{name:<14} {row['verdict']:<13} {row['states_explored']:>8} {row['best_ms']:>10.2f}"
        )
    print("\n(timing is indicative only — not a benchmark gate)")


if __name__ == "__main__":
    main()
