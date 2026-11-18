"""Selected verdicts use dependency proofs, with separate global diagnostics."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    Add,
    AlwaysHolds,
    DeadActions,
    Entity,
    Event,
    Field,
    Initial,
    Invariant,
    NoDeadEnd,
    Or,
    Reachable,
    Set,
    Spec,
)
from analint.cli import app
from analint.mcp_server import check_spec, trace_spec
from analint.reporter.json_reporter import result_to_dict
from analint.validator import validate, validate_spec
from analint.validator.engine import prepare_model
from analint.validator.exploration_service import trace_query

BENCHMARK = Path(__file__).resolve().parents[1] / "benchmarks/independent_checks.py"


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(BENCHMARK.read_text())
    return path


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("check", ["safe_a", "bounded_a"])
def test_independent_failure_is_diagnostic_not_a_supporting_proof(
    entry, monkeypatch, sliced, cache, check
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    spec = prepare_model(entry).spec
    before = repr(spec)
    full = validate_spec(spec, sliced=sliced, cache=cache)
    assert full.verdict == "FAIL"
    for _ in range(2):  # also exercise disk cache hits and repeat request isolation
        chosen = validate_spec(spec, checks=[check], sliced=sliced, cache=cache)
        assert chosen.verdict == chosen.effective_verdict(strict=True) == "PASS"
        assert [r.invariant_id for r in chosen.invariant_results] == ["bounded_a"]
        assert "invariant:bounded_b" in chosen.selection["not_selected"]
        assert chosen.selection["model_actions"] == ["bump_a", "bump_b"]
        assert any(f.location == "invariant:bounded_b" for f in chosen.model_findings)
        assert not chosen.exploration_findings
        assert chosen.model_coverage["capped_explorations"] == 0
        selected_results = chosen.query_results or chosen.invariant_results
        full_results = full.query_results if chosen.query_results else full.invariant_results
        assert selected_results[0].status == full_results[0].status
    assert repr(spec) == before
    assert stable(result_to_dict(full)) == stable(
        result_to_dict(validate_spec(spec, sliced=sliced, cache=cache))
    )


def test_only_dependency_proofs_are_executed(entry, monkeypatch):
    from analint.validator import explorer

    verified = []
    original = explorer._verify_grouped

    def record(pairs):
        verified.extend(inv.id for inv, _ in pairs)
        return original(pairs)

    monkeypatch.setattr(explorer, "_verify_grouped", record)
    result = validate(entry, checks=["safe_a"])
    assert result.verdict == "PASS"
    assert verified == ["bounded_a"]


@pytest.mark.parametrize("sliced", [False, True])
def test_unrelated_action_defects_are_separate_but_related_ones_block(entry, sliced):
    spec = prepare_model(entry).spec
    a = next(cls for cls in spec.entities if cls.__name__ == "A")
    b = next(cls for cls in spec.entities if cls.__name__ == "B")
    spec.actions[1].post = [b.n == 0]
    report = validate_spec(spec, checks=["safe_a"], sliced=sliced)
    assert report.verdict == "PASS"
    assert any(
        f.location == "action:bump_b" and f.severity == "ERROR" for f in report.model_findings
    )
    assert report.effective_verdict(strict=True) == "PASS"
    spec.actions[0].post = [a.n == 0]
    broken = validate_spec(spec, checks=["safe_a"], sliced=sliced)
    assert broken.verdict == "FAIL"
    assert any(f.location == "action:bump_a" for f in broken.exploration_findings)
    assert all(f.location != "action:bump_a" for f in broken.model_findings)


def test_transitive_support_and_other_flow_actions_are_not_removed(entry):
    spec = prepare_model(entry).spec
    a = next(cls for cls in spec.entities if cls.__name__ == "A")
    b = next(cls for cls in spec.entities if cls.__name__ == "B")
    spec.invariants.append(Invariant(a.n <= b.n, id="bridge"))
    result = validate_spec(spec, checks=["safe_a"])
    assert result.verdict == "FAIL"
    assert set(result.selection["supporting"]) == {
        "invariant:bounded_a",
        "invariant:bounded_b",
        "invariant:bridge",
    }
    assert result.selection["dependencies"]["query:safe_a"]["actions"] == ["bump_a", "bump_b"]


@pytest.mark.parametrize("sliced", [False, True])
def test_own_roots_do_not_borrow_canonical_proofs(entry, sliced):
    spec = prepare_model(entry).spec
    a = next(cls for cls in spec.entities if cls.__name__ == "A")
    b = next(cls for cls in spec.entities if cls.__name__ == "B")
    spec.initial = Initial(given=[a(n=3), b()])
    spec.invariants[0].expression = a.n <= 2  # broken canonically, valid along the own-root path
    spec.actions[0].pre = [a.n < 2]
    spec.queries[0].given = [a(), b()]
    report = validate_spec(spec, checks=["safe_a"], sliced=sliced)
    assert report.verdict == "PASS"
    assert report.invariant_results == []
    assert report.selection["supporting"] == []
    assert report.query_results[0].states_explored > 1
    assert validate_spec(spec).verdict == "FAIL"


@pytest.mark.parametrize("sliced", [False, True])
def test_root_legality_is_a_dependency_even_outside_the_property_slice(entry, sliced):
    spec = prepare_model(entry).spec
    b = next(cls for cls in spec.entities if cls.__name__ == "B")
    spec.queries[0].given = [b(n=20)]
    report = validate_spec(spec, checks=["safe_a"], sliced=sliced)
    assert report.verdict == "FAIL"
    assert any(f.location == "invariant:bounded_b" for f in report.exploration_findings)


def test_diagnostic_routing_keeps_different_query_roots_separate():
    class A(Entity):
        n: int = Field(0, ge=0, le=1)

    class B(Entity):
        n: int = Field(0, ge=0, le=1)

    bad = Action(id="bad_b", pre=[B.n == 1], effect=[Add(B.n, 1)])
    spec = Spec(
        id="roots",
        name="Roots",
        actions=[bad],
        queries=[
            AlwaysHolds(A.n == 0, id="a", given=[B(n=1)]),
            AlwaysHolds(B.n == 0, id="b", given=[B(n=0)]),
        ],
    )
    for sliced in (False, True):
        result = validate_spec(spec, checks=["a", "b"], sliced=sliced)
        assert result.verdict == "PASS"
        assert any(f.location == "action:bad_b" for f in result.model_findings)
        assert not result.exploration_findings


@pytest.mark.parametrize("kind", [NoDeadEnd, DeadActions])
def test_global_queries_retain_global_support_and_findings(entry, kind):
    spec = prepare_model(entry).spec
    a = next(cls for cls in spec.entities if cls.__name__ == "A")
    query = DeadActions(id="global") if kind is DeadActions else NoDeadEnd(a.n == 0, id="global")
    spec.queries.append(query)
    report = validate_spec(spec, checks=["global"])
    assert report.verdict == "FAIL"
    assert "invariant:bounded_b" in report.selection["supporting"]
    assert report.selection["dependencies"]["query:global"]["whole_model"] is True


def test_irrelevant_exclusions_and_budget_are_diagnostic():
    class Signal(Event):
        ok: bool

    class A(Entity):
        n: int = Field(0, ge=0, le=1)

    class B(Entity):
        n: int = Field(0, ge=0, le=100)

    spec = Spec(
        id="excluded",
        name="Excluded",
        actions=[
            Action(id="a", pre=[A.n < 1], effect=[Add(A.n, 1)]),
            Action(id="b", pre=[B.n < 100], effect=[Add(B.n, 1)]),
            Action(id="event", pre=[Signal.ok], effect=[Set(B.n, 0)]),
        ],
        queries=[AlwaysHolds(A.n <= 1, id="safe")],
    )
    result = validate_spec(spec, checks=["safe"], max_states=3)
    assert result.verdict == "PASS"
    assert result.model_coverage["capped_explorations"] > 0
    assert "event" in result.model_coverage["excluded_actions"]
    assert not result.selection["excluded_actions"]
    assert result.model_findings
    assert validate_spec(spec, checks=["safe"], max_states=1).verdict == "INCONCLUSIVE"
    spec.actions[2].effect = [Set(A.n, 0)]  # now the exclusion affects the property
    assert validate_spec(spec, checks=["safe"], max_states=3).verdict == "INCONCLUSIVE"


def test_cli_mcp_trace_compact_and_library_agree(entry):
    expected = result_to_dict(validate(entry, checks=["safe_a"]))
    assert expected["verdict"] == "PASS" and expected["model_findings"]
    cli = CliRunner().invoke(
        app, ["check", str(entry), "--check", "safe_a", "--strict", "-f", "json"]
    )
    assert cli.exit_code == 0, cli.output
    assert stable(json.loads(cli.stdout)) == stable(expected)
    assert stable(check_spec(str(entry), checks=["safe_a"])) == stable(expected)
    compact = check_spec(str(entry), checks=["safe_a"], compact=True)
    assert compact["model_findings"][0]["count"] > 0
    assert compact["verdict"] == "PASS"
    terminal = CliRunner().invoke(app, ["check", str(entry), "--check", "safe_a"])
    assert terminal.exit_code == 0
    assert "MODEL DIAGNOSTICS" in terminal.stdout and "bounded_b" in terminal.stdout
    native = trace_query(entry, "safe_a")
    assert native["verification_verdict"] == native["status"] == "PASS"
    assert native["selection"] == expected["selection"]
    assert stable(native["model_findings"]) == stable(expected["model_findings"])
    assert native == trace_spec(str(entry), "safe_a")


def test_tlc_export_only_filters_defect_assertions_not_transitions(entry):
    from analint.backends.tla import Target, export_tla
    from analint.validator.explorer import build_canonical_initials

    spec = prepare_model(entry).spec
    roots, _ = build_canonical_initials(spec)
    full = export_tla(spec, roots, target=Target("always", spec.queries[0].predicate))
    selected = export_tla(
        spec, roots, target=Target("always", spec.queries[0].predicate), defect_actions={"bump_a"}
    )
    assert selected.module == full.module
    assert selected.actions == full.actions
    assert "INVARIANT NoDefect_A0_bump_a" in selected.config
    assert "INVARIANT NoDefect_A1_bump_b" not in selected.config
    assert "INVARIANT NoDefect_A1_bump_b" in full.config


def test_unknown_dependency_analysis_keeps_the_whole_model(entry, monkeypatch):
    from analint.validator import slicing

    def unknown(*args):
        raise slicing._Unsliceable("future AST")

    monkeypatch.setattr(slicing, "_pred_vars", unknown)
    result = validate(entry, checks=["safe_a"])
    assert result.verdict == "FAIL"
    assert result.selection["dependencies"]["query:safe_a"]["whole_model"] is True
    assert "invariant:bounded_b" in result.selection["supporting"]


def test_proved_bridge_does_not_pull_in_unneeded_transitive_proofs(entry, monkeypatch):
    from analint.validator import explorer

    spec = prepare_model(entry).spec
    a = next(cls for cls in spec.entities if cls.__name__ == "A")
    b = next(cls for cls in spec.entities if cls.__name__ == "B")
    spec.invariants.append(Invariant(Or(a.n >= 0, b.n >= 0), id="bridge"))
    proved = []
    original = explorer._verify_grouped

    def record(pairs):
        proved.extend(inv.id for inv, _ in pairs)
        return original(pairs)

    monkeypatch.setattr(explorer, "_verify_grouped", record)
    result = validate_spec(spec, checks=["safe_a"])
    assert result.verdict == "PASS"
    assert result.selection["supporting"] == ["invariant:bounded_a", "invariant:bridge"]
    assert proved == ["bounded_a", "bridge"]
    assert any(f.location == "invariant:bounded_b" for f in result.model_findings)
    # A direct invariant proved without constraints needs no supporting proof,
    # including the bridge that mentions the same field.
    proved.clear()
    direct = validate_spec(spec, checks=["bounded_a"])
    assert direct.verdict == "PASS" and direct.selection["supporting"] == []
    assert proved == ["bounded_a"]


def test_known_relevant_defect_is_not_hidden_by_another_check_budget():
    class A(Entity):
        n: int = 0

    class B(Entity):
        n: int = Field(0, ge=0, le=2)

    spec = Spec(
        id="budget",
        name="Budget",
        actions=[
            Action(id="b", effect=[Add(B.n, 1)]),
        ],
        queries=[
            AlwaysHolds(A.n == 0, id="a", max_states=10),
            Reachable(B.n == 0, id="b", max_states=1),
        ],
    )
    a_only = validate_spec(spec, checks=["query:a"])
    assert a_only.verdict == "PASS" and a_only.model_findings
    both = validate_spec(spec, checks=["query:a", "query:b"])
    assert all(q.status == "PASS" for q in both.query_results)
    assert both.verdict == "FAIL"
    assert any(f.location == "action:b" for f in both.exploration_findings)
