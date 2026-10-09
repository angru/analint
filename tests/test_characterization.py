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

from analint.models.entity import all_fields
from analint.models.scope import InstanceRef, context_key_label
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


def _labelled_state(ctx: dict) -> tuple:
    """The pre-compaction state key: (label, field, value) per field, sorted by
    label; an absent scoped slot contributes only its presence flag."""
    items = []
    for key in sorted(ctx, key=context_key_label):
        values = ctx[key].__dict__
        label = context_key_label(key)
        if isinstance(key, InstanceRef):
            present = values.get("_analint_present", True)
            items.append((label, "@present", present))
            if not present:
                continue
        entity_cls = key.entity_cls if isinstance(key, InstanceRef) else key
        items.extend((label, f, values.get(f)) for f in sorted(all_fields(entity_cls)))
    return tuple(items)


def _query_fingerprint(spec, query, cache: dict) -> tuple[dict, str, dict]:
    # one cache per example: explorations are deterministic, so queries over
    # the same roots and budget share one instead of re-exploring it
    before = set(cache)
    qr = run_query(query, spec, cache)
    new = set(cache) - before
    exp = cache[new.pop()] if new else _exploration_for(spec, query, cache)
    incomplete = []
    if exp.capped:
        incomplete.append("capped")
    if exp.excluded:
        incomplete.append("excluded-semantics")
    # hash labelled states, so the baseline is independent of the in-memory
    # state-key encoding (explorer.state_key stores values only)
    labelled = {key: _labelled_state(ctx) for key, ctx in exp.states.items()}
    states_hash = _digest(labelled.values())
    edges_hash = _digest((labelled[src], aid, labelled[dst]) for src, aid, dst in exp.edges)
    roots_hash = _digest((labelled[key], index) for key, index in exp.roots.items())
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


def _exploration_for(spec, query, cache: dict):
    """The cached exploration a query reused (same roots and budget)."""
    from analint.validator.explorer import resolve_query_initials, state_key

    initials, _ = resolve_query_initials(query, spec)
    roots = tuple(dict.fromkeys(state_key(ctx) for ctx in initials))
    return cache[(roots, query.max_states)]


def _characterize(path: Path) -> dict:
    """Deterministic, order- and timing-independent fingerprint of one example."""
    # the monolithic path is the semantic oracle; slicing is gated against it
    # by tests/test_slicing.py
    result = validate(path, sliced=False)
    spec = build_spec(path)[0]
    assert spec is not None
    queries = {}
    explorations = {}
    cache: dict = {}
    for query in spec.queries:
        query_fingerprint, exploration_id, exploration_fingerprint = _query_fingerprint(
            spec, query, cache
        )
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
                "actions_run": fr.actions_run,
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
