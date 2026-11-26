"""Measure native BFS builds independently of graph lookup and property counts."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint.backends.tlc import TlcResult
from analint.cli import app
from analint.mcp_server import check_spec
from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer, tlc_fallback
from analint.validator.engine import validate


@pytest.fixture
def counter(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text("""from analint import Action, Add, AlwaysHolds, Entity, Field, Invariant, Reachable, Spec

class Counter(Entity):
    n: int = Field(0, ge=0, le=2)

tick = Action(pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
bounded = Invariant(Counter.n <= 2)
done = Reachable(Counter.n == 2)
safe = AlwaysHolds(Counter.n >= 0)
offset = Reachable(Counter.n == 2, given=[Counter(n=1)], max_states=1)
spec = Spec(id="test", name="Test", actions=[tick], invariants=[bounded], queries=[done, safe, offset])
""")
    return path


def without_work(result):
    payload = result_to_dict(result)
    payload.pop("exploration_work", None)
    for check in payload["queries"] + payload["invariants"]:
        check.pop("elapsed_ms")
    return payload


def test_shared_graph_is_charged_once_and_disk_hits_cost_no_new_search(
    counter, tmp_path, monkeypatch
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    baseline = validate(counter, sliced=False)
    assert "exploration_work" not in result_to_dict(baseline)
    cold = validate(counter, sliced=False, explain_work=True, cache=True)
    warm = validate(counter, sliced=False, explain_work=True, cache=True)
    assert without_work(baseline) == without_work(cold) == without_work(warm)
    for result, origin, fresh in [(cold, "built", 4), (warm, "disk_cache", 0)]:
        work = result.exploration_work
        assert work["total_search_states"] == work["native_states_built"] == fresh
        assert work["max_reported_states_per_check"] == 3
        full, capped = work["native_graphs"]
        assert full["origin"] == capped["origin"] == origin
        assert full["complete"] and full["states"] == 3
        assert capped["capped"] and not capped["complete"] and capped["states"] == 1
        assert capped["roots"] == capped["budget"] == 1
        assert capped["root_source"] == "given"
        properties = work["properties"]
        for name in ("invariant:bounded", "query:done", "query:safe"):
            assert properties[name]["native_graph_id"] == full["id"]
        assert properties["query:offset"]["native_graph_id"] == capped["id"]


def test_projected_and_discarded_searches_are_counted_at_build_time(monkeypatch):
    counted = []
    original = explorer._explore

    def observe(*args, **kwargs):
        exp = original(*args, **kwargs)
        counted.append(exp.state_count)
        return exp

    monkeypatch.setattr(explorer, "_explore", observe)
    result = validate(
        Path("examples/branch_protection"),
        checks=["merge_is_achievable"],
        max_states=3,
        explain_work=True,
    )
    report = result.exploration_work
    assert len(counted) > 1
    assert any(g["projection"] for g in report["native_graphs"])
    assert [g["states"] for g in report["native_graphs"]] == counted
    assert report["native_states_built"] == sum(counted) > report["max_reported_states_per_check"]


@pytest.mark.parametrize(
    "outcome", [TlcResult("ok", distinct_states=3), TlcResult("error", output="timeout")]
)
def test_tlc_work_and_missing_statistics(counter, monkeypatch, outcome):
    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: ("java", "test.jar"))
    monkeypatch.setattr(tlc_fallback, "run_tlc", lambda *args, **kwargs: outcome)
    result = validate(
        counter,
        checks=["safe"],
        sliced=False,
        max_states=1,
        tlc=True,
        tlc_timeout=5,
        explain_work=True,
    )
    work = result.exploration_work
    assert work["tlc_requested"]
    assert work["tlc_runs"]
    for run in work["tlc_runs"]:
        assert run["distinct_states"] == outcome.distinct_states
        assert run["timeout_seconds"] == 5
        assert run["complete"] == (outcome.status == "ok")
    expected = (
        None
        if outcome.distinct_states is None
        else work["native_states_built"] + len(work["tlc_runs"]) * 3
    )
    assert work["total_search_states"] == expected


def test_cli_and_mcp_report_the_same_graphs(counter):
    args = ["check", str(counter), "--no-slice", "--explain-work"]
    runner = CliRunner()
    assert "Native BFS states built" in runner.invoke(app, args).stdout
    cli = json.loads(runner.invoke(app, [*args, "-f", "json"]).stdout)
    mcp = check_spec(str(counter), slice=False, compact=True, explain_work=True)
    assert cli["exploration_work"] == mcp["exploration_work"]
