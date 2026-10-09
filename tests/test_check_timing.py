"""Timing attribution uses a fake clock, never hardware-dependent thresholds."""

import pytest

from analint import Action, Add, Entity, Field, Invariant, Reachable, Spec
from analint.reporter.base import ValidationResult
from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer
from analint.validator.slicing import SliceAnalysis


@pytest.fixture
def model():
    class Counter(Entity):
        value: int = Field(0, ge=0, le=2)

    return Spec(
        id="timing",
        name="Timing",
        entities=[Counter],
        actions=[Action(id="tick", pre=[Counter.value < 2], effect=[Add(Counter.value, 1)])],
        invariants=[
            Invariant(Counter.value >= 0, id="nonnegative"),
            Invariant(Counter.value <= 2, id="bounded"),
        ],
        queries=[Reachable(Counter.value == 2, id="two")],
    )


@pytest.fixture
def fake_clock(monkeypatch):
    now = [0.0]
    original = explorer.explore

    def timed_explore(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] += 0.025
        return result

    monkeypatch.setattr(explorer, "perf_counter", lambda: now[0])
    monkeypatch.setattr(explorer, "explore", timed_explore)


@pytest.mark.parametrize("sliced", [False, True])
def test_shared_query_exploration_is_charged_once(model, fake_clock, sliced):
    cache = {}
    analysis = SliceAnalysis(model) if sliced else None
    first = explorer.run_query(model.queries[0], model, cache, analysis=analysis)
    second = explorer.run_query(model.queries[0], model, cache, analysis=analysis)
    assert first.elapsed_ms == pytest.approx(25)
    assert second.elapsed_ms == 0
    assert first.status == second.status == "PASS"


@pytest.mark.parametrize("sliced", [False, True])
def test_shared_invariant_exploration_is_charged_once(model, fake_clock, sliced):
    initials, _ = explorer.build_canonical_initials(model)
    results, _ = explorer.verify_invariants(
        model, initials, analysis=SliceAnalysis(model) if sliced else None
    )
    assert [r.elapsed_ms for r in results] == pytest.approx([25, 0])
    assert all(r.status == "PASS" for r in results)


def test_invariant_timing_includes_constrained_retry(model, fake_clock):
    counter = model.entities[0]
    model.invariants = [Invariant(counter.value <= 1, id="too_small")]
    initials, _ = explorer.build_canonical_initials(model)
    (result,), _ = explorer.verify_invariants(model, initials, analysis=SliceAnalysis(model))
    assert result.status == "FAIL"
    assert result.elapsed_ms == pytest.approx(50)


def test_json_serializes_measured_checks_and_omits_unchecked_timing(model, fake_clock):
    query = explorer.run_query(model.queries[0], model, {})
    unchecked, _ = explorer.verify_invariants(model, None, build_error="no root")
    result = ValidationResult(
        spec_id=model.id, spec_name=model.name, query_results=[query], invariant_results=unchecked
    )
    data = result_to_dict(result)
    assert data["queries"][0]["elapsed_ms"] == 25
    assert all("elapsed_ms" not in inv for inv in data["invariants"])


def test_rejected_query_is_timed(model, fake_clock, monkeypatch):
    monkeypatch.setattr(explorer, "resolve_query_initials", lambda *args: (None, "no root"))
    result = explorer.run_query(model.queries[0], model, {})
    assert result.status == "FAIL"
    assert result.elapsed_ms == 0
