"""Fixed initial relations exercise the same fail-closed paths as varying roots."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import Absent, Bound, Entity, Field, Initial, Invariant, Min, Reachable, Scope, Spec
from analint.cli import app
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import prepare_model, validate
from analint.validator.exploration_service import explore_path, trace_query
from analint.validator.explorer import build_canonical_initials, build_initial_relation, run_query
from analint.validator.structural import validate_structural

runner = CliRunner()


@pytest.fixture
def fixed_spec(tmp_path):
    reference = Path(__file__).resolve().parents[1] / "docs" / "dsl.md"
    blocks = re.findall(
        r'^```python title="fixed-root-spec.py"\n(.*?)^```$',
        reference.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(blocks) == 1
    entry = tmp_path / "spec.py"
    entry.write_text(blocks[0])
    return entry


def _semantic_report(report):
    if isinstance(report, dict):
        return {k: _semantic_report(v) for k, v in report.items() if k != "elapsed_ms"}
    if isinstance(report, list):
        return [_semantic_report(v) for v in report]
    return report


@pytest.mark.parametrize("kwargs", [{}, {"vary": []}], ids=["omitted", "empty"])
def test_fixed_initial_is_one_filtered_candidate_and_copies_given(kwargs):
    class Box(Entity):
        n: int = Field(0, ge=0, le=3)

    given = Box(n=2)
    relation = Initial(**kwargs, given=[given], where=[Box.n == 2], max_candidates=1)
    roots, error = build_initial_relation(Spec(id="s", name="S", entities=[Box]), relation)
    assert error is None
    assert len(roots) == 1
    assert roots[0][Box].n == 2
    roots[0][Box].n = 1
    assert given.n == 2


def test_empty_initial_uses_the_single_defaults_root():
    class Box(Entity):
        n: int = 3

    spec = Spec(id="s", name="S", initial=Initial(), invariants=[Invariant(Box.n == 3, id="n")])
    roots, error = build_canonical_initials(spec)
    assert error is None
    assert len(roots) == 1
    assert roots[0][Box].n == 3


@pytest.mark.parametrize("budget", [0, -1, 1.5])
def test_fixed_initial_keeps_candidate_budget_validation(budget):
    with pytest.raises(TypeError, match="max_candidates must be a positive integer"):
        Initial(max_candidates=budget)


@pytest.mark.parametrize("supplied", [False, True])
def test_fixed_canonical_root_requires_missing_values_and_derives_the_entity(supplied):
    class Required(Entity):
        value: int

    spec = Spec(
        id="s",
        name="S",
        initial=Initial(given=[Required(value=3)] if supplied else []),
        invariants=[Invariant(Required.value > 0, id="positive")],
    )
    assert Required in spec.entities
    roots, error = build_canonical_initials(spec)
    if supplied:
        assert error is None
        assert len(roots) == 1
        assert roots[0][Required].value == 3
    else:
        assert roots is None
        assert "without full defaults" in error


def test_fixed_initial_givens_still_reject_duplicate_instances():
    class Box(Entity):
        n: int = 0

    spec = Spec(
        id="s",
        name="S",
        initial=Initial(given=[Box(n=1), Box(n=2)]),
        invariants=[Invariant(Box.n >= 0, id="nonnegative")],
    )
    errors = [f for f in validate_structural(spec) if f.severity == "ERROR"]
    assert len(errors) == 1
    assert "Initial.given lists Box twice" in errors[0].message


def test_fixed_initial_empty_aggregate_filter_is_an_error_not_a_pass():
    class Item(Entity):
        value: int = 1

    items = Scope(Item, keys=["a"], id="items")
    item = Bound("item", items)
    relation = Initial(given=[Absent(items["a"])], where=[Min(item, item.value) > 0])
    query = Reachable(True, id="q", initial=relation)
    spec = Spec(id="s", name="S", queries=[query])
    result = run_query(query, spec, cache={})
    assert result.status == "FAIL"
    assert "where evaluation error" in result.findings[0].message


@pytest.mark.parametrize("sliced", [True, False], ids=["sliced", "whole"])
def test_fixed_roots_across_check_explore_and_trace(fixed_spec, sliced):
    flags = [] if sliced else ["--no-slice"]
    result = runner.invoke(app, ["check", str(fixed_spec), "--strict", "-f", "json", *flags])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["verdict"] == "PASS"
    assert report["invariants"][0]["status"] == "PASS"
    queries = {item["id"]: item for item in report["queries"]}
    assert queries["created"]["trace"] == ["create"]
    assert queries["already_created"]["trace"] == []
    assert queries["created"]["states_explored"] == (2 if sliced else 4)

    canonical = explore_path(fixed_spec, include_graph=True).to_dict()
    own = explore_path(fixed_spec, query_id="already_created").to_dict()
    assert canonical["completeness"]["complete"] is True
    assert canonical["summary"]["roots"] == own["summary"]["roots"] == 1
    assert canonical["summary"]["states"] == 4
    assert own["summary"]["states"] == 2
    witness = trace_query(fixed_spec, "created", sliced=sliced)
    assert [step["action"] for step in witness["steps"]] == ["create"]
    assert witness["final_state"]["Counter.n"] == 1
    own_witness = trace_query(fixed_spec, "already_created", sliced=sliced)
    assert own_witness["status"] == "PASS"
    assert own_witness["root"]["index"] == 1
    assert own_witness["steps"] == []
    assert own_witness["final_state"]["Counter.n"] == 1


def test_fixed_roots_survive_disk_cache_round_trip(fixed_spec, tmp_path, monkeypatch):
    from analint.validator import explorer

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(cache_dir))
    fresh = _semantic_report(result_to_dict(validate(fixed_spec)))
    cold = _semantic_report(result_to_dict(validate(fixed_spec, cache=True)))
    assert list(cache_dir.rglob("*.json.z"))

    def unexpected_exploration(*args):
        pytest.fail("a warm fixed-root check should reuse the stored explorations")

    monkeypatch.setattr(explorer, "_explore", unexpected_exploration)
    warm = _semantic_report(result_to_dict(validate(fixed_spec, cache=True)))
    assert fresh == cold == warm


def test_fixed_roots_keep_budget_exhaustion_distinct_from_failure(fixed_spec):
    report = result_to_dict(validate(fixed_spec, max_states=1))
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["passed"] is False
    assert report["invariants"][0]["status"] == "INCONCLUSIVE"
    queries = {item["id"]: item["status"] for item in report["queries"]}
    assert queries == {"created": "INCONCLUSIVE", "already_created": "PASS"}


@pytest.mark.parametrize("sliced", [True, False], ids=["sliced", "whole"])
def test_invalid_fixed_root_has_initial_state_counterexample(fixed_spec, sliced):
    source = fixed_spec.read_text()
    original = "initial=Initial(given=[Limit(max_created=1), Absent(one), Absent(spare)])"
    assert source.count(original) == 1
    fixed_spec.write_text(
        source.replace(original, original.replace("given=[", "given=[Counter(n=1), "))
    )
    result = validate(fixed_spec, sliced=sliced)
    assert result.verdict == "FAIL"
    assert all(scenario.passed for scenario in result.scenario_results)
    assert result.invariant_results[0].status == "FAIL"
    trace = trace_query(fixed_spec, "balanced", sliced=sliced)
    assert trace["status"] == "FAIL"
    assert trace["root"] is not None
    assert trace["steps"] == []
    assert trace["final_state"]["Counter.n"] == 1


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "query"])
@pytest.mark.parametrize(
    ("predicate", "message"),
    [("Box.n == 1", "matches no states"), ("Box.n > 'broken'", "where evaluation error")],
    ids=["empty", "evaluation-error"],
)
def test_fixed_relations_fail_closed_across_surfaces(tmp_path, canonical, predicate, message):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Entity, Initial, Invariant, Reachable, Spec\n"
        "class Box(Entity):\n    n: int = 0\n"
        f"relation = Initial(where=[{predicate}])\n"
        "safe = Invariant(Box.n >= 0)\n"
        f"query = Reachable(Box.n == 0{'' if canonical else ', initial=relation'})\n"
        f"spec = Spec(id='s', name='S', initial={'relation' if canonical else 'None'},\n"
        "            invariants=[safe], queries=[query])\n"
    )
    result = runner.invoke(app, ["check", str(entry), "-f", "json"])
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["verdict"] == "FAIL"
    assert report["passed"] is False
    assert message in result.output
    if not canonical:
        assert report["queries"][0]["status"] == "FAIL"
    for args in (["explore", str(entry), "--query", "query"], ["trace", "query", "-p", str(entry)]):
        response = runner.invoke(app, [*args, "-f", "json"])
        assert response.exit_code == 3, response.output
        error = json.loads(response.output)
        assert error["schema"] == "analint.error/v1"
        assert message in response.output


def test_fixed_roots_keep_tlc_state_counts_and_fallback_verdicts(fixed_spec):
    from analint.backends.tla import Target, export_tla
    from analint.backends.tlc import TlcUnavailable, find_tlc, run_tlc
    from analint.validator.explorer import explore

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    spec = prepare_model(fixed_spec).spec
    roots, error = build_canonical_initials(spec)
    assert error is None
    outcome = run_tlc(export_tla(spec, roots, target=Target("always", True)))
    assert outcome.status == "ok", outcome.output
    assert outcome.distinct_states == len(explore(spec, roots, 30).states) == 4

    full = validate(fixed_spec)
    decided = validate(fixed_spec, max_states=1, tlc=True, tlc_timeout=30)
    assert full.verdict == decided.verdict == "PASS"
    for field in ("invariant_results", "query_results"):
        assert [r.status for r in getattr(decided, field)] == [
            r.status for r in getattr(full, field)
        ]
    assert decided.invariant_results[0].backend == "tlc"
    assert decided.query_results[0].backend == "tlc"
