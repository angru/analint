"""Characterization (golden) snapshot of every example spec.

The behavioural baseline that de-risks engine refactors (notably the upcoming
transition kernel). It pins, per example:

- the overall verdict;
- each scenario by id -> PASS/FAIL (not just counts: two scenarios swapping
  results would otherwise hide);
- each query's status and reachable-state count, plus the edge count and stable
  hashes of the canonical state set and edge multiset — so a graph that changes
  shape while keeping the same state count is still caught;
- traces, normalized findings, roots, fired/excluded actions and explicit
  completeness reasons (review ca537a2);
- each world invariant verified over the canonical model -> status, state count,
  trace and normalized findings.

Intentionally failing examples (coin overflow, trollbridge) are part of the
baseline. Timing is NOT asserted (hardware-dependent, research/18 §7) — see
scripts/bench.py.

The snapshot is characterization, not normative semantics: a refactor that is
*meant* to change behaviour (see tests/snapshots/README.md for the kernel's
expected deltas) regenerates it under review, never mechanically.

    UPDATE_SNAPSHOT=1 uv run pytest tests/test_characterization.py
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from analint.validator.engine import build_spec, validate
from analint.validator.explorer import run_query

EXAMPLES = Path(__file__).parent.parent / "examples"
SNAPSHOT = Path(__file__).parent / "snapshots" / "examples.json"


def _digest(items) -> str:
    """Order-independent, cross-run-stable hash of a collection of values."""
    blob = "\n".join(sorted(repr(item) for item in items))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _finding_digest(findings) -> str:
    return _digest((str(f.severity), f.location, f.message) for f in findings)


def _query_fingerprint(spec, query) -> tuple[dict, str, dict]:
    cache: dict = {}
    qr = run_query(query, spec, cache)
    exp = next(iter(cache.values()))
    incomplete = []
    if exp.capped:
        incomplete.append("capped")
    if exp.excluded:
        incomplete.append("excluded-semantics")
    states_hash = _digest(exp.states)
    edges_hash = _digest(exp.edges)
    roots_hash = _digest(exp.roots.items())
    findings_hash = _finding_digest(exp.findings)
    exploration_fingerprint = {
        "states": len(exp.states),
        "edges": len(exp.edges),
        "states_hash": states_hash,
        "edges_hash": edges_hash,
        "roots": len(exp.roots),
        "roots_hash": roots_hash,
        "findings_hash": findings_hash,
        "fired": sorted(exp.fired),
        "excluded": dict(sorted(exp.excluded.items())),
        "incomplete": incomplete,
    }
    exploration_id = _digest(exploration_fingerprint.items())
    query_fingerprint = {
        "status": str(qr.status),
        "states": qr.states_explored,
        "exploration": exploration_id,
        "trace": qr.trace,
        "findings_hash": _finding_digest(qr.findings),
    }
    return query_fingerprint, exploration_id, exploration_fingerprint


def _characterize(path: Path) -> dict:
    """Deterministic, order- and timing-independent fingerprint of one example."""
    result = validate(path)
    spec = build_spec(path)[0]
    assert spec is not None
    queries = {}
    explorations = {}
    for query in spec.queries:
        query_fingerprint, exploration_id, exploration_fingerprint = _query_fingerprint(spec, query)
        queries[query.id] = query_fingerprint
        explorations.setdefault(exploration_id, exploration_fingerprint)
    return {
        "verdict": str(result.verdict),
        "warnings": result.warning_count,
        "scenarios": {
            sr.scenario_id: {
                "status": "PASS" if sr.passed else "FAIL",
                "rules": sr.rules_count,
                "findings_hash": _finding_digest(sr.findings),
            }
            for sr in result.scenario_results
        },
        "queries": queries,
        "explorations": explorations,
        "invariants": {
            ir.invariant_id: {
                "status": str(ir.status),
                "states": ir.states_explored,
                "trace": ir.trace,
                "findings_hash": _finding_digest(ir.findings),
            }
            for ir in result.invariant_results
        },
        "flows": {
            fr.flow_id: {
                "passed": fr.passed,
                "steps_run": fr.steps_run,
                "trace": fr.trace,
                "findings_hash": _finding_digest(fr.findings),
            }
            for fr in result.flow_results
        },
    }


def _example_dirs() -> list[str]:
    # an example is a directory with a spec.py (skips __pycache__ and the runner)
    return sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir() and (p / "spec.py").exists())


def test_update_snapshot_when_requested():
    """Not a real assertion: regenerates the committed snapshot on demand."""
    if not os.environ.get("UPDATE_SNAPSHOT"):
        pytest.skip("set UPDATE_SNAPSHOT=1 to regenerate the snapshot")
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {name: _characterize(EXAMPLES / name) for name in _example_dirs()}
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("name", _example_dirs())
def test_example_matches_snapshot(name: str):
    baseline = json.loads(SNAPSHOT.read_text())
    assert name in baseline, f"{name} missing from snapshot — run UPDATE_SNAPSHOT=1"
    assert _characterize(EXAMPLES / name) == baseline[name]


def test_snapshot_covers_every_example():
    baseline = json.loads(SNAPSHOT.read_text())
    assert set(baseline) == set(_example_dirs())
