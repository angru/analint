"""A completed unconstrained safety proof needs no invariant-pruning support."""

from pathlib import Path

import pytest

from analint import Initial
from analint.validator.engine import prepare_model, validate_spec

BENCHMARK = Path(__file__).resolve().parents[1] / "benchmarks/safety_bridge.py"


@pytest.fixture
def spec():
    prepared = prepare_model(BENCHMARK)
    assert not prepared.load_errors and not prepared.has_structural_errors
    return prepared.spec.model_copy(deep=True)


@pytest.mark.parametrize("check", ["safe_a", "never_overflow"])
@pytest.mark.parametrize("roots", ["canonical", "given", "given_any", "initial"])
def test_safety_pass_discharges_bridge_support(spec, check, roots):
    a, b = spec.entities
    query = next(q for q in spec.queries if q.id == check)
    if roots == "given":
        query.given = [a(), b()]
    elif roots == "given_any":
        query.given_any = [[a(), b()], [a(n=1), b(n=1)]]
    elif roots == "initial":
        query.initial = Initial(given=[a(), b()])
    before = repr(spec)
    result = validate_spec(spec, checks=[check])
    assert result.verdict == result.effective_verdict(strict=True) == "PASS"
    assert result.selection["supporting"] == []
    assert result.invariant_results == []
    assert result.selection["dependencies"][f"query:{check}"] == {
        "actions": ["bump_a"],
        "invariants": [],
        "whole_model": False,
    }
    assert result.query_results[0].states_explored == (7 if roots == "given_any" else 4)
    assert result.selection["model_actions"] == ["bump_a", "bump_b"]
    assert any(f.location == "invariant:bounded_b" for f in result.model_findings)
    assert not result.exploration_findings
    assert repr(spec) == before
    assert validate_spec(spec).verdict == "FAIL"


@pytest.mark.parametrize("check", ["safe_a", "never_overflow"])
def test_no_slice_keeps_conservative_support(spec, check):
    result = validate_spec(spec, checks=[check], sliced=False)
    assert result.verdict == "FAIL"
    assert set(result.selection["supporting"]) == {
        "invariant:bounded_a",
        "invariant:bridge",
        "invariant:bounded_b",
    }


@pytest.mark.parametrize("check", ["safe_a", "never_overflow"])
def test_speculative_counterexample_is_rechecked_under_constraints(spec, check):
    from analint import AlwaysHolds, Invariant, Unreachable

    a = spec.entities[0]
    spec.invariants.append(Invariant(a.n < 2, id="stop"))
    spec.queries = [AlwaysHolds(a.n <= 2, id="safe_a"), Unreachable(a.n == 3, id="never_overflow")]
    result = validate_spec(spec, checks=[check])
    query = result.query_results[0]
    assert query.status == "PASS" and query.trace is None  # the speculative state 3 is unreachable
    assert result.verdict == "FAIL"  # the required constraint itself breaks at state 2
    assert "invariant:stop" in result.selection["supporting"]
    assert result.selection["dependencies"][f"query:{check}"]["invariants"]


@pytest.mark.parametrize("check", ["safe_a", "never_overflow"])
def test_real_counterexample_keeps_a_constrained_trace(spec, check):
    from analint import AlwaysHolds, Unreachable
    from analint.validator.explorer import run_query

    a = spec.entities[0]
    spec.queries = [AlwaysHolds(a.n < 3, id="safe_a"), Unreachable(a.n == 3, id="never_overflow")]
    query = next(q for q in spec.queries if q.id == check)
    result = validate_spec(spec, checks=[check]).query_results[0]
    whole = run_query(query, spec, {})
    assert result.status == whole.status == "FAIL"
    assert result.trace == whole.trace
    assert len(result.trace) > 3 and "bump_b" in result.trace


@pytest.mark.parametrize("roots", ["given", "given_any", "initial"])
def test_illegal_roots_cannot_be_projected_away(spec, roots):
    a, b = spec.entities
    query = spec.queries[0]
    if roots == "given":
        query.given = [a(), b(n=20)]
    elif roots == "given_any":
        # Same query projection: legal representative must not hide the bad root.
        query.given_any = [[a(), b()], [a(), b(n=20)]]
    else:
        query.initial = Initial(given=[a(), b(n=20)])
    result = validate_spec(spec, checks=["safe_a"])
    assert result.verdict == "FAIL"
    assert any(f.location == "invariant:bounded_b" for f in result.exploration_findings)
    assert "bump_b" in result.selection["dependencies"]["query:safe_a"]["actions"]


def test_caps_do_not_discharge_support_and_budget_override_is_respected(spec):
    spec.queries[0].max_states = 1
    small = validate_spec(spec, checks=["safe_a"])
    assert small.query_results[0].status == "INCONCLUSIVE"
    assert small.selection["supporting"]
    large = validate_spec(spec, checks=["safe_a"], max_states=100)
    assert large.verdict == "PASS" and large.selection["supporting"] == []


def test_excluded_action_that_writes_the_property_blocks_proof(spec):
    from analint import Action, Event, Set

    class Signal(Event):
        flag: bool = False

    a = spec.entities[0]
    # Rebuild declarations to include the newly referenced event explicitly.
    spec.actions.append(Action(id="signal", pre=[Signal.flag], effect=[Set(a.n, 1)]))
    spec.events.append(Signal)
    result = validate_spec(spec, checks=["safe_a"])
    assert result.query_results[0].status == "INCONCLUSIVE"
    assert "signal" in result.selection["excluded_actions"]
    assert result.selection["supporting"]


@pytest.mark.parametrize("defect", ["post", "payload", "bound"])
def test_relevant_transition_defects_still_block(spec, defect):
    from analint import Add, Event, Field

    a = spec.entities[0]
    if defect == "post":
        spec.actions[0].post = [a.n == 0]
    elif defect == "payload":

        class Payload(Event):
            n: int = Field(0, le=0)

        spec.actions[0].emits = [Payload(n=a.n)]
        spec.events.append(Payload)
    else:
        spec.actions[0].effect = [Add(a.n, 4)]
    result = validate_spec(spec, checks=["safe_a"])
    assert result.verdict == "FAIL"
    assert any(f.location == "action:bump_a" for f in result.exploration_findings)
    assert result.selection["supporting"]


def test_speculative_own_root_defects_never_inherit_canonical_trust():
    from analint import Action, Add, AlwaysHolds, Entity, Field, Invariant, Set, Spec

    class State(Entity):
        n: int = Field(0, ge=0, le=3)
        active: bool = False

    spec = Spec(
        id="trust",
        name="Trust",
        actions=[
            Action(id="advance", pre=[State.active, State.n < 3], effect=[Add(State.n, 1)]),
            Action(
                id="unreachable_defect",
                pre=[State.n == 2],
                effect=[Set(State.n, 3)],
                post=[State.n == 0],
            ),
        ],
        invariants=[Invariant(State.n < 2, id="stop")],
        queries=[
            AlwaysHolds(State.n <= 3, id="safe", given=[State(active=True)]),
        ],
    )
    result = validate_spec(spec, checks=["stop", "safe"])
    assert result.invariant_results[0].status == "PASS"  # only the canonical state is reachable
    assert result.query_results[0].status == "PASS"
    assert result.verdict == "FAIL"  # own-root exploration really violates stop
    assert any(f.location == "invariant:stop" for f in result.exploration_findings)
    assert not any(
        f.location == "action:unreachable_defect"
        for f in [*result.exploration_findings, *result.model_findings]
    )


def test_requested_invariant_and_witness_support_are_never_dropped(spec):
    from analint import Reachable

    a = spec.entities[0]
    explicit = validate_spec(spec, checks=["safe_a", "bounded_a"])
    assert [r.invariant_id for r in explicit.invariant_results] == ["bounded_a"]
    assert explicit.selection["supporting"] == []
    spec.queries.append(Reachable(a.n == 3, id="witness"))
    joint = validate_spec(spec, checks=["safe_a", "witness"])
    assert joint.verdict == "FAIL" and joint.selection["supporting"]
    assert joint.selection["dependencies"]["query:safe_a"]["invariants"] == []
    assert joint.selection["dependencies"]["query:witness"]["invariants"]


def test_bridge_measurement_counts_real_search_work(spec, monkeypatch):
    from analint.validator import explorer, safety

    run = explorer._explore
    counts = []

    def counted(*args, **kwargs):
        graph = run(*args, **kwargs)
        counts.append(len(graph.states))
        return graph

    monkeypatch.setattr(explorer, "_explore", counted)
    with monkeypatch.context() as baseline:
        baseline.setattr(safety, "prove_query", lambda *a, **kw: None)
        old = validate_spec(spec, checks=["safe_a"])
    assert len(old.invariant_results) == 3
    assert old.query_results[0].states_explored == 81
    assert sum(counts) == 190
    counts.clear()
    improved = validate_spec(spec, checks=["safe_a"])
    assert improved.invariant_results == []
    assert improved.query_results[0].states_explored == 4
    assert sum(counts) == 85  # includes the 81-state all-action diagnostic coverage


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(BENCHMARK.read_text())
    return path


def test_cache_and_check_trace_surfaces_agree(entry, monkeypatch):
    import json

    from typer.testing import CliRunner

    from analint.cli import app
    from analint.mcp_server import check_spec, trace_spec
    from analint.reporter.json_reporter import result_to_dict
    from analint.validator import explorer
    from analint.validator.engine import validate
    from analint.validator.exploration_service import trace_query

    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    fresh = _stable(result_to_dict(validate(entry, checks=["safe_a"])))
    assert fresh["verdict"] == "PASS" and fresh["selection"]["supporting"] == []
    cold = _stable(result_to_dict(validate(entry, checks=["safe_a"], cache=True)))
    # Cache is an invocation option, so compare reports after matching that metadata.
    fresh["selection"]["options"]["cache"] = True
    assert cold == fresh
    with monkeypatch.context() as cached:

        def miss(*args, **kwargs):
            pytest.fail("warm safety proof / diagnostic cache missed")

        cached.setattr(explorer, "_explore", miss)
        assert _stable(result_to_dict(validate(entry, checks=["safe_a"], cache=True))) == cold
    cli = CliRunner().invoke(
        app, ["check", str(entry), "--check", "safe_a", "--cache", "--strict", "-f", "json"]
    )
    assert cli.exit_code == 0, cli.output
    assert _stable(json.loads(cli.output)) == cold
    assert _stable(check_spec(str(entry), checks=["safe_a"], cache=True)) == cold
    compact = check_spec(str(entry), checks=["safe_a"], cache=True, compact=True)
    assert compact["verdict"] == "PASS" and compact["model_findings"]
    trace = trace_query(entry, "safe_a", cache=True)
    assert trace["status"] == trace["verification_verdict"] == "PASS"
    assert trace["selection"] == cold["selection"]
    assert trace["model_findings"] == cold["model_findings"]
    assert trace == trace_spec(str(entry), "safe_a", cache=True)


@pytest.fixture
def tlc_available():
    from analint.backends.tlc import TlcUnavailable, find_tlc

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("check", ["safe_a", "never_overflow"])
@pytest.mark.parametrize("own", [False, True])
def test_tlc_can_complete_the_safety_proof(spec, tlc_available, check, own):
    if own:
        query = next(q for q in spec.queries if q.id == check)
        query.given = [entity() for entity in spec.entities]
    native = validate_spec(spec, checks=[check])
    result = validate_spec(spec, checks=[check], max_states=1, tlc=True)
    assert result.verdict == native.verdict == "PASS"
    assert result.selection["supporting"] == [] and result.invariant_results == []
    assert result.query_results[0].backend == "tlc"
    assert result.query_results[0].states_explored == native.query_results[0].states_explored
    assert result.query_results[0].slice == native.query_results[0].slice


def test_tlc_check_trace_and_compact_reports_agree(entry, tlc_available):
    from analint.mcp_server import check_spec, trace_spec
    from analint.validator.engine import validate
    from analint.validator.exploration_service import trace_query

    result = validate(entry, checks=["safe_a"], max_states=1, tlc=True)
    trace = trace_query(entry, "safe_a", max_states=1, tlc=True)
    assert trace["status"] == trace["verification_verdict"] == result.verdict == "PASS"
    assert trace["backend"] == "tlc" and trace["state_trace_available"] is False
    assert trace["selection"] == result.selection
    assert trace_spec(str(entry), "safe_a", max_states=1, tlc=True)["selection"] == result.selection
    compact = check_spec(str(entry), checks=["safe_a"], max_states=1, tlc=True, compact=True)
    assert compact["verdict"] == "PASS" and compact["selection"]["supporting"] == []


def test_tlc_counterexample_is_rechecked_with_constraints(spec, tlc_available, monkeypatch):
    from analint import AlwaysHolds, Invariant
    from analint.validator import tlc_fallback

    a = spec.entities[0]
    spec.invariants.append(Invariant(a.n < 2, id="stop"))
    spec.queries = [AlwaysHolds(a.n <= 2, id="safe_a")]
    calls = []
    decide = tlc_fallback._decide_query

    def record(model, result, query, piece, *args):
        decide(model, result, query, piece, *args)
        calls.append(([inv.id for inv in piece.invariants], result.status))

    monkeypatch.setattr(tlc_fallback, "_decide_query", record)
    result = validate_spec(spec, checks=["safe_a"], max_states=1, tlc=True)
    assert calls[0] == ([], "FAIL")
    assert calls[-1][1] == "PASS" and "stop" in calls[-1][0]
    assert result.query_results[0].status == "PASS" and result.query_results[0].trace is None
    assert result.selection["supporting"] and result.verdict == "FAIL"


def test_tlc_only_transition_defect_remains_blocking(spec, tlc_available):
    from analint.reporter.base import Code

    a = spec.entities[0]
    spec.actions[0].post = [a.n == 0]
    result = validate_spec(spec, checks=["safe_a"], max_states=1, tlc=True)
    assert result.verdict == "FAIL"
    assert result.selection["supporting"]
    assert any(f.code == Code.TLC_TRANSITION_DEFECT for f in result.exploration_findings)


def test_tlc_unavailability_does_not_discharge_support(spec, monkeypatch):
    from analint.backends import tlc
    from analint.reporter.base import Code

    def unavailable():
        raise tlc.TlcUnavailable("test backend unavailable")

    monkeypatch.setattr(tlc, "find_tlc", unavailable)
    # The normal fallback imports this symbol at module scope.
    monkeypatch.setattr("analint.validator.tlc_fallback.find_tlc", unavailable)
    result = validate_spec(spec, checks=["safe_a"], max_states=1, tlc=True)
    assert result.query_results[0].status == "INCONCLUSIVE"
    assert result.selection["supporting"]
    assert any(f.code == Code.TLC_UNAVAILABLE for f in result.exploration_findings)


def test_tlc_errors_do_not_discharge_support(spec, monkeypatch):
    from analint.backends import tlc
    from analint.reporter.base import Code
    from analint.validator import tlc_fallback

    monkeypatch.setattr(tlc, "find_tlc", lambda: ("java", "test.jar"))
    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: ("java", "test.jar"))
    monkeypatch.setattr(
        tlc_fallback, "run_tlc", lambda *a, **kw: tlc.TlcResult("error", output="timeout")
    )
    result = validate_spec(spec, checks=["safe_a"], max_states=1, tlc=True, tlc_timeout=0.1)
    assert result.query_results[0].status == "INCONCLUSIVE"
    assert result.selection["supporting"]
    assert any(f.code == Code.TLC_FAILED for f in result.query_results[0].findings)


def test_unsupported_tlc_export_is_not_a_proof(spec, tlc_available):
    from analint.reporter.base import Code

    a = spec.entities[0]
    spec.invariants = []  # isolate the unsupported query export from invariant fallback
    spec.queries[0].predicate = a.n <= 3.0  # floats are native literals, not TLC literals
    result = validate_spec(spec, checks=["safe_a"], max_states=1, tlc=True)
    assert result.verdict == result.query_results[0].status == "INCONCLUSIVE"
    assert any(f.code == Code.TLC_NOT_EXPORTED for f in result.query_results[0].findings)


def test_a_missing_root_value_cannot_produce_a_vacuous_proof():
    from analint import AlwaysHolds, Entity, Spec
    from analint.validator.safety import prove_query
    from analint.validator.slicing import SliceAnalysis

    class Required(Entity):
        n: int

    query = AlwaysHolds(Required.n >= 0, id="safe")
    model = Spec(id="missing", name="Missing root", queries=[query])
    assert prove_query(query, model, SliceAnalysis(model)) is None
    assert validate_spec(model, checks=["safe"]).verdict == "FAIL"
