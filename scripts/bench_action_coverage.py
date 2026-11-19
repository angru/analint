#!/usr/bin/env python
"""Measure action-slice work, including reuse (informational, never a timing gate).

Run against the same spec/interpreter before and after a slicing change, with no
concurrent tests. --cache with a fresh ANALINT_CACHE_DIR reports cold then warm
work. The interpreter's installed analint is measured, so this script can also
be run with a baseline checkout's Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

import analint
from analint.validator import explorer
from analint.validator.engine import validate
from analint.validator.slicing import Slice


def measure(path: Path, *, cache: bool) -> dict:
    actual_states = []
    returned = []  # pin graphs while counting reuse by identity
    actual = explorer._explore
    sliced = explorer.explore_slice

    def explore(*args: Any, **kwargs: Any) -> explorer.Exploration:
        graph = actual(*args, **kwargs)
        actual_states.append(len(graph.states))
        return graph

    def slice_request(*args: Any, **kwargs: Any) -> tuple[explorer.Exploration, Slice]:
        graph, piece = sliced(*args, **kwargs)
        returned.append(graph)
        return graph, piece

    with (
        patch.object(explorer, "_explore", explore),
        patch.object(explorer, "explore_slice", slice_request),
    ):
        start = perf_counter()
        report = validate(path, cache=cache)
        elapsed = perf_counter() - start
    checks = [*report.query_results, *report.invariant_results]
    unique = {id(graph): graph for graph in returned}
    return {
        "seconds": round(elapsed, 4),
        "verdict": str(report.verdict),
        "per_check_states": {
            **{f"query:{r.query_id}": r.states_explored for r in report.query_results},
            **{f"invariant:{r.invariant_id}": r.states_explored for r in report.invariant_results},
        },
        "max_reported_states": max((r.states_explored for r in checks), default=0),
        "actual_exploration_calls": len(actual_states),
        "actual_explored_states": sum(actual_states),
        "actual_states_by_call": actual_states,
        "slice_requests": len(returned),
        "reused_slice_requests": len(returned) - len(unique),
        "unique_slice_graph_states": sum(len(g.states) for g in unique.values()),
        "states_returned_including_reuse": sum(len(g.states) for g in returned),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cache", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "python": sys.version,
                "analint": analint.__file__,
                "spec": str(args.path.resolve()),
                "cache": args.cache,
                "runs": [measure(args.path, cache=args.cache) for _ in range(args.repeats)],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
