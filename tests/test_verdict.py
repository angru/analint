"""Three-valued verdict: INCONCLUSIVE must never read as a green PASS
(research/18 §2.2)."""

from pathlib import Path

from typer.testing import CliRunner

from analint.cli import app
from analint.reporter.base import QueryResult, ScenarioResult, ValidationResult
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import validate

INCONCLUSIVE = Path(__file__).parent / "fixtures" / "inconclusive"
runner = CliRunner()


def _result(**kw) -> ValidationResult:
    return ValidationResult(spec_id="s", spec_name="S", **kw)


def test_verdict_pass_when_everything_holds():
    r = _result(query_results=[QueryResult(query_id="q", kind="Reachable", status="PASS")])
    assert r.verdict == "PASS"
    assert not r.has_inconclusive


def test_verdict_fail_takes_precedence():
    r = _result(
        query_results=[
            QueryResult(query_id="a", kind="AlwaysHolds", status="FAIL"),
            QueryResult(query_id="b", kind="Unreachable", status="INCONCLUSIVE"),
        ]
    )
    assert r.verdict == "FAIL"


def test_verdict_inconclusive_when_only_budget_ran_out():
    r = _result(
        query_results=[QueryResult(query_id="q", kind="Unreachable", status="INCONCLUSIVE")]
    )
    assert r.verdict == "INCONCLUSIVE"
    assert r.has_inconclusive
    assert not r.has_errors  # the key bug: this used to read as green


def test_failed_scenario_is_fail_not_inconclusive():
    r = _result(scenario_results=[ScenarioResult(scenario_id="s", scenario_name="S", passed=False)])
    assert r.verdict == "FAIL"


def test_json_reports_verdict_and_passed_false_on_inconclusive():
    r = _result(
        query_results=[QueryResult(query_id="q", kind="Unreachable", status="INCONCLUSIVE")]
    )
    payload = result_to_dict(r)
    assert payload["verdict"] == "INCONCLUSIVE"
    assert payload["passed"] is False
    assert payload["summary"]["queries_inconclusive"] == 1


def test_inconclusive_spec_end_to_end_is_not_green():
    result = validate(INCONCLUSIVE)
    assert result.verdict == "INCONCLUSIVE"
    assert any(qr.status == "INCONCLUSIVE" for qr in result.query_results)


def test_cli_exit_code_4_on_inconclusive():
    res = runner.invoke(app, ["check", str(INCONCLUSIVE)])
    assert res.exit_code == 4, res.output
