#!/usr/bin/env python
"""Measure M4–M6 with the same budget in sliced and whole-model verification.

    uv run python scripts/bench_broker.py --json
    uv run python scripts/bench_broker.py --max-states 10000 --repeats 3 --json

Runtime is informational. Capped checks remain INCONCLUSIVE; state counts are
per check, never summed across reused explorations. Optional memory measurement
runs separately so tracemalloc does not distort the reported wall time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
import tracemalloc
from pathlib import Path

from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import build_spec, validate

ROOT = Path(__file__).resolve().parent.parent


def measure(increment: str, *, sliced: bool, budget: int, repeats: int, memory: bool) -> dict:
    path = ROOT / "benchmarks" / "broker" / f"{increment}.py"
    spec, _, errors = build_spec(path)
    assert spec is not None and not errors, errors
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        result = validate(path, sliced=sliced, max_states=budget)
        times.append(time.perf_counter() - started)
    payload = result_to_dict(result)
    peak = None
    if memory:
        tracemalloc.start()
        validate(path, sliced=sliced, max_states=budget)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return {
        "increment": increment,
        "sliced": sliced,
        "max_states": budget,
        "entities": len(spec.entities),
        "lifecycles": len(spec.lifecycles),
        "actions": len(spec.actions),
        "scenarios": len(spec.scenarios),
        "verdict": payload["verdict"],
        "min_seconds": round(min(times), 6),
        "median_seconds": round(statistics.median(times), 6),
        "peak_memory_bytes": peak,
        "summary": payload["summary"],
        "checks": [
            {"kind": section, **check}
            for section in ("invariants", "queries")
            for check in payload[section]
        ],
        "structural": payload["structural"],
        "exploration_findings": payload["exploration"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-states", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--increment", choices=["m4", "m5", "m6"], action="append")
    args = parser.parse_args()
    if args.max_states <= 0 or args.repeats <= 0:
        parser.error("max-states and repeats must be positive")
    sources = sorted((ROOT / "benchmarks" / "broker").glob("*.py"))
    sources += sorted((ROOT / "examples" / "broker").glob("*.py"))
    digest = hashlib.sha256()
    for source in sources:
        digest.update(str(source.relative_to(ROOT)).encode())
        digest.update(source.read_bytes())
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    )
    engine_digest = hashlib.sha256()
    for source in sorted((ROOT / "src" / "analint").rglob("*.py")):
        engine_digest.update(str(source.relative_to(ROOT)).encode())
        engine_digest.update(source.read_bytes())
    rows = [
        measure(
            increment,
            sliced=sliced,
            budget=args.max_states,
            repeats=args.repeats,
            memory=args.memory,
        )
        for increment in args.increment or ["m4", "m5", "m6"]
        for sliced in (True, False)
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "meta": {
                        "revision": revision,
                        "working_tree_dirty": dirty,
                        "model_sha256": digest.hexdigest(),
                        "engine_sha256": engine_digest.hexdigest(),
                        "python": platform.python_version(),
                        "platform": platform.platform(),
                        "repeats": args.repeats,
                        "load": "preloaded import closure",
                    },
                    "rows": rows,
                },
                indent=2,
            )
        )
        return
    for row in rows:
        largest = max(c["states_explored"] for c in row["checks"])
        print(
            f"{row['increment']} {'sliced' if row['sliced'] else 'whole':6} "
            f"{row['verdict']:12} {row['actions']:3} actions "
            f"{largest:6} states/check {row['median_seconds']:.3f} s"
        )


if __name__ == "__main__":
    main()
