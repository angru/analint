"""Characterization (golden) snapshot of every example spec.

This is the behavioural baseline that de-risks refactors of the engine: the
transition kernel must reproduce the same verdicts, scenario counts and
reachable-state counts for every example, including the intentionally-failing
ones (trollbridge is deliberately broken; coin's overflow query is expected to
fail — it finds a real bug). Timing is NOT asserted here (hardware-dependent);
use ``scripts/bench.py`` for that.

Regenerate after an intended behaviour change:

    UPDATE_SNAPSHOT=1 uv run pytest tests/test_characterization.py
"""

import json
import os
from pathlib import Path

import pytest

from analint.validator.engine import validate

EXAMPLES = Path(__file__).parent.parent / "examples"
SNAPSHOT = Path(__file__).parent / "snapshots" / "examples.json"


def _characterize(path: Path) -> dict:
    """Deterministic outcome of validating one example — order-independent and
    free of wall-clock timing, so it is a stable regression oracle."""
    result = validate(path)
    return {
        "verdict": str(result.verdict),
        "scenarios_passed": result.passed_count,
        "scenarios_failed": result.failed_count,
        "warnings": result.warning_count,
        "queries": {
            qr.query_id: {"status": str(qr.status), "states": qr.states_explored}
            for qr in result.query_results
        },
    }


def _example_dirs() -> list[str]:
    return sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir())


def _current() -> dict:
    return {name: _characterize(EXAMPLES / name) for name in _example_dirs()}


def test_update_snapshot_when_requested():
    """Not a real assertion: regenerates the committed snapshot on demand."""
    if not os.environ.get("UPDATE_SNAPSHOT"):
        pytest.skip("set UPDATE_SNAPSHOT=1 to regenerate the snapshot")
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(_current(), ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("name", _example_dirs())
def test_example_matches_snapshot(name: str):
    baseline = json.loads(SNAPSHOT.read_text())
    assert name in baseline, f"{name} missing from snapshot — run UPDATE_SNAPSHOT=1"
    assert _characterize(EXAMPLES / name) == baseline[name]


def test_snapshot_covers_every_example():
    baseline = json.loads(SNAPSHOT.read_text())
    assert set(baseline) == set(_example_dirs())
