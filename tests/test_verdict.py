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


# ── fail-closed aggregation (review e76b3ce, P1) ─────────────────────────────────


def test_not_checked_is_not_a_silent_pass():
    r = _result(query_results=[QueryResult(query_id="q", kind="X", status="NOT_CHECKED")])
    assert r.verdict == "INCONCLUSIVE"
    assert not r.is_successful


def test_unknown_status_fails_closed():
    for status in ("TYPO", "maybe", ""):
        r = _result(query_results=[QueryResult(query_id="q", kind="X", status=status)])
        assert r.verdict == "FAIL", status
        assert not r.is_successful


def test_is_successful_only_on_clean_pass():
    assert _result(query_results=[QueryResult(query_id="q", kind="X", status="PASS")]).is_successful
    assert not _result(
        query_results=[QueryResult(query_id="q", kind="X", status="INCONCLUSIVE")]
    ).is_successful


# ── --strict consistency: JSON verdict and exit code must agree (review P2) ──────


def test_strict_warning_makes_json_and_exit_agree():
    # Dedicated fixture with a guaranteed warning, so the test does not silently
    # lose coverage if an example is cleaned up (review 584d819 P3).
    warns = Path(__file__).parent / "fixtures" / "warns"
    result = validate(warns)
    assert result.warning_count >= 1
    plain = result_to_dict(result, strict=False)
    strict = result_to_dict(result, strict=True)
    assert plain["passed"] is True
    assert strict["passed"] is False
    assert strict["verdict"] == "FAIL"
    assert runner.invoke(app, ["check", str(warns)]).exit_code == 0
    assert runner.invoke(app, ["check", str(warns), "--strict"]).exit_code == 1


# ── Budget exhaustion vs not checkable; the --max-states override ─────────────

_BOUNDED = """
from analint import Action, Add, Entity, Field, Invariant, Spec, Unreachable


class Gauge(Entity):
    n: int = Field(0, ge=0, le=20)


class Needs(Entity):
    x: int  # no default: the canonical state cannot be built for it


tick = Action(id="tick", pre=[Gauge.n < 20], effect=[Add(Gauge.n, 1)])
in_range = Invariant(Gauge.n <= 20)
never_99 = Unreachable(Gauge.n == 99, id="never_99")
spec = Spec(id="b", name="B", entities=[Gauge], actions=[tick], invariants=[in_range])
"""


def test_summary_separates_inconclusive_from_not_checked(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(_BOUNDED)
    capped = result_to_dict(validate(entry, max_states=5))["summary"]
    assert (capped["invariants_inconclusive"], capped["invariants_not_checked"]) == (1, 0)

    # Needs has no default, so the canonical state cannot be built at all
    unbuildable = tmp_path / "unbuildable" / "spec.py"
    unbuildable.parent.mkdir()
    unbuildable.write_text(
        _BOUNDED.replace("entities=[Gauge]", "entities=[Gauge, Needs]")
        .replace("invariants=[in_range]", "invariants=[in_range, needs_x]")
        .replace("spec = Spec(", "needs_x = Invariant(Needs.x >= 0)\nspec = Spec(")
    )
    summary = result_to_dict(validate(unbuildable))["summary"]
    assert (summary["invariants_inconclusive"], summary["invariants_not_checked"]) == (0, 2)
    assert summary["invariants_unchecked"] == 2  # v1 field: their sum


def test_max_states_override_does_not_mutate_the_model(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        _BOUNDED.replace("invariants=[in_range])", "invariants=[in_range], queries=[never_99])")
    )

    capped = validate(entry, max_states=5)
    assert [q.status for q in capped.query_results] == ["INCONCLUSIVE"]
    assert capped.query_results[0].states_explored == 5

    again = validate(entry)  # same loaded objects: the override must not stick
    assert [q.status for q in again.query_results] == ["PASS"]
    assert [i.status for i in again.invariant_results] == ["PASS"]


def test_cli_max_states_reaches_every_exploration():
    res = runner.invoke(app, ["check", str(INCONCLUSIVE), "--max-states", "7", "-f", "json"])
    assert res.exit_code == 4, res.output
    assert '"states_explored": 7' in res.output

    bad = runner.invoke(app, ["check", str(INCONCLUSIVE), "--max-states", "0"])
    assert bad.exit_code == 2
