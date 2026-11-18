"""TLC defect paths and repeated blocking attribution across report sections."""

import json

import pytest
from typer.testing import CliRunner

from analint.backends.tlc import TlcResult, TlcUnavailable, find_tlc
from analint.cli import app
from analint.reporter.base import Code
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import validate
from analint.validator.exploration_service import trace_query


@pytest.fixture(params=["query", "invariant"])
def kind(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["initial", "later"])
def later(request):
    return request.param


@pytest.fixture
def entry(tmp_path, kind, later):
    path = tmp_path / "spec.py"
    constructor = "AlwaysHolds" if kind == "query" else "Invariant"
    collection = "queries" if kind == "query" else "invariants"
    path.write_text(f"""from analint import Action, Add, AlwaysHolds, Entity, Field, Invariant, Spec

class Counter(Entity):
    n: int = Field(0, ge=0, le=2)

tick = Action(pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
paint = Action(pre=[Counter.n == {2 if later else 0}], effect=[Add(Counter.n, 0)],
               post=[Counter.n < 0])
safe = {constructor}(Counter.n <= 2)
spec = Spec(id="reporting", name="Reporting", actions=[tick, paint], {collection}=[safe])
""")
    return path


@pytest.fixture
def simulated_tlc(monkeypatch, later):
    from analint.backends import tlc
    from analint.validator import tlc_fallback

    monkeypatch.setattr(tlc, "find_tlc", lambda: ("java", "test.jar"))
    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: ("java", "test.jar"))

    def defect(export, **kwargs):
        action = next(name for name, label in export.actions.items() if label == "paint")
        return TlcResult(
            "violation", violated=f"NoDefect_{action}", trace=["tick", "tick"] if later else []
        )

    monkeypatch.setattr(tlc_fallback, "run_tlc", defect)


def defects(findings):
    return [f for f in findings if f["code"] == Code.TLC_TRANSITION_DEFECT]


def check_report(report, kind, later, compact):
    assert report["verdict"] == "FAIL" and report["passed"] is False
    [property_result] = report["queries" if kind == "query" else "invariants"]
    assert property_result["status"] == "INCONCLUSIVE"
    assert property_result["trace"] is None
    assert "backend" not in property_result  # TLC found a defect, not a property decision
    [attributed] = defects(property_result["findings"])
    [blocking] = defects(report["exploration"])
    assert attributed == blocking
    if compact:
        assert attributed["count"] == 1
        [finding] = attributed["examples"]
    else:
        finding = attributed
    assert finding["location"] == f"{kind}:safe"
    expected_path = "tick → tick → paint" if later else "(initial state) → paint"
    assert finding["message"].endswith(f"in paint: {expected_path}")
    return finding


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("sliced", [False, True])
def test_tlc_only_defect_stays_blocking_across_reports(
    entry, kind, later, simulated_tlc, selected, sliced
):
    selection = {"checks": [f"{kind}:safe"]} if selected else {}
    options = {"max_states": 1, "sliced": sliced, **selection}
    assert validate(entry, **options).verdict == "INCONCLUSIVE"
    result = validate(entry, tlc=True, **options)
    assert result.effective_verdict(strict=True) == "FAIL"
    for compact in (False, True):
        report = result_to_dict(result, compact=compact)
        check_report(report, kind, later, compact)
        args = ["check", str(entry), "--max-states", "1", "--tlc", "--strict", "-f", "json"]
        if selected:
            args += ["--check", f"{kind}:safe"]
        if not sliced:
            args.append("--no-slice")
        if compact:
            args.append("--compact")
        cli = CliRunner().invoke(app, args)
        assert cli.exit_code == 1, cli.output
        check_report(json.loads(cli.output), kind, later, compact)

    trace = trace_query(entry, f"{kind}:safe", max_states=1, sliced=sliced, tlc=True)
    assert trace["status"] == "INCONCLUSIVE" and trace["verification_verdict"] == "FAIL"
    assert trace["witness"] is None and trace["steps"] == []
    assert "backend" not in trace and "action_trace" not in trace
    [finding] = defects(trace["findings"])
    assert finding == check_report(result_to_dict(result), kind, later, False)


def test_real_tlc_defect_reporting_matches_native_failure(entry, kind, later):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    native = validate(entry, checks=[f"{kind}:safe"])
    assert native.verdict == "FAIL"
    assert any(f.code == Code.POSTCONDITION_VIOLATED for f in native.exploration_findings)
    for selected in (False, True):
        selection = {"checks": [f"{kind}:safe"]} if selected else {}
        result = validate(entry, max_states=1, tlc=True, **selection)
        check_report(result_to_dict(result), kind, later, False)
