"""Reachable needs a path from every root, not just a multi-source BFS witness."""

import json

import pytest
from typer.testing import CliRunner

from analint import Action, Add, Entity, Event, Field, Initial, Reachable, Set, Spec
from analint.backends.tlc import TlcResult, TlcUnavailable, find_tlc
from analint.cli import app
from analint.reporter.base import Code
from analint.validator.engine import validate, validate_spec
from analint.validator.exploration_service import trace_query
from analint.validator.explorer import run_query


def _model(source, reverse=False):
    class Box(Entity):
        enabled: bool = True
        done: bool = False

    finish = Action(id="finish", pre=[Box.enabled], effect=[Set(Box.done, True)])
    roots = [[Box(enabled=x)] for x in ([False, True] if reverse else [True, False])]
    query = Reachable(Box.done, id="done")
    spec = Spec(id="roots", name="Roots", actions=[finish], queries=[query])
    if source == "canonical":
        spec.initial = Initial(vary=[Box.enabled])
    elif source == "initial":
        query.initial = Initial(vary=[Box.enabled])
    else:
        query.given_any = roots
    return spec, query


@pytest.mark.parametrize("source", ["canonical", "initial", "given_any"])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_partial_reachability_fails_with_all_root_forms(
    source, sliced, reverse, tmp_path, monkeypatch
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    spec, _ = _model(source, reverse)
    reports = []
    for cache in (False, True, True):
        result = validate_spec(spec, sliced=sliced, cache=cache)
        [query] = result.query_results
        assert result.verdict == query.status == "FAIL"
        assert query.trace == []
        assert any(f.code == Code.NOT_REACHABLE and "init #" in f.message for f in query.findings)
        assert any(
            f.code == Code.INITIAL_STATE and "enabled=False" in f.message for f in query.findings
        )
        reports.append([(f.code, f.message) for f in query.findings])
    assert reports[0] == reports[1] == reports[2]


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("start", [0, 1])
def test_converging_paths_and_root_to_root_edges(sliced, start):
    class Counter(Entity):
        n: int = Field(0, ge=0, le=3)

    tick = Action(id="tick", pre=[Counter.n < 3], effect=[Add(Counter.n, 1)])
    query = Reachable(Counter.n == 3, id="done", given_any=[[Counter(n=start)], [Counter(n=2)]])
    spec = Spec(id="merge", name="Merge", actions=[tick], queries=[query])
    result = validate_spec(spec, sliced=sliced)
    assert result.verdict == "PASS"
    assert result.query_results[0].trace == ["tick"]  # representative BFS witness


@pytest.mark.parametrize("sliced", [False, True])
def test_duplicate_and_projected_roots(sliced):
    class Box(Entity):
        done: bool = False
        irrelevant: bool = False

    finish = Action(id="finish", effect=[Set(Box.done, True)])
    query = Reachable(
        Box.done,
        id="done",
        given_any=[
            [Box()],
            [Box()],
            [Box(irrelevant=True)],
            [Box(done=True)],
        ],
    )
    spec = Spec(id="duplicate", name="Duplicate", actions=[finish], queries=[query])
    assert validate_spec(spec, sliced=sliced).verdict == "PASS"


@pytest.mark.parametrize("all_done", [False, True])
@pytest.mark.parametrize("excluded", [False, True])
def test_partial_proofs_stay_inconclusive_but_all_root_witnesses_are_final(all_done, excluded):
    class Box(Entity):
        done: bool = False
        other: bool = False

    class Signal(Event):
        go: bool = True

    wait = Action(id="wait", pre=[Signal.go], effect=[Set(Box.done, True)])
    tick = Action(id="tick", effect=[Set(Box.other, True)])
    query = Reachable(
        Box.done,
        id="done",
        max_states=100 if excluded else 2,
        given_any=[[Box(done=True)], [Box(done=all_done, other=True)]],
    )
    spec = Spec(id="partial", name="Partial", actions=[wait if excluded else tick], queries=[query])
    result = run_query(query, spec, cache={})
    assert result.status == ("PASS" if all_done else "INCONCLUSIVE")
    if not all_done:
        assert result.trace is None


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text("""from analint import Action, Entity, Reachable, Set, Spec
class Box(Entity):
    enabled: bool = True
    done: bool = False
finish = Action(pre=[Box.enabled], effect=[Set(Box.done, True)])
done = Reachable(Box.done, given_any=[[Box(enabled=True)], [Box(enabled=False)]])
spec = Spec(id="roots", name="Roots", actions=[finish], queries=[done])
""")
    return path


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_cli_check_and_trace_identify_the_unreachable_root(entry, sliced, selected):
    args = ["check", str(entry), "-f", "json"]
    if not sliced:
        args.append("--no-slice")
    if selected:
        args += ["--check", "query:done"]
    cli = CliRunner().invoke(app, args)
    assert cli.exit_code == 1, cli.output
    assert json.loads(cli.output)["queries"][0]["status"] == "FAIL"
    trace = trace_query(entry, "done", sliced=sliced)
    assert trace["status"] == "FAIL"
    assert trace["steps"] == []
    assert trace["final_state"]["Box.enabled"] is False


@pytest.mark.parametrize("second", ["ok", "violation", "error", "defect"])
def test_tlc_must_decide_every_root(entry, monkeypatch, second):
    from analint.validator import tlc_fallback

    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: ("java", "test.jar"))
    calls = []

    def run(export, **kwargs):
        calls.append(export)
        if len(calls) % 2 == 1:
            return TlcResult("violation", violated="Target", trace=["finish"], distinct_states=2)
        if second == "defect":
            action = next(iter(export.actions))
            return TlcResult("violation", violated=f"NoDefect_{action}", distinct_states=1)
        return TlcResult(
            second,
            violated="Target" if second == "violation" else None,
            trace=["finish"] if second == "violation" else [],
            distinct_states=1,
        )

    monkeypatch.setattr(tlc_fallback, "run_tlc", run)
    result = validate(entry, max_states=1, tlc=True)
    [query] = result.query_results
    expected = {
        "ok": "FAIL",
        "violation": "PASS",
        "error": "INCONCLUSIVE",
        "defect": "INCONCLUSIVE",
    }
    assert query.status == expected[second]
    assert len(calls) == 2
    if second in {"error", "defect"}:
        assert query.backend is None and query.trace is None
        if second == "defect":
            assert result.verdict == "FAIL"
    else:
        assert query.backend == "tlc" and query.states_explored == 3
        if second == "ok":
            assert any("init #2" in f.message for f in query.findings)
            assert query.trace is None
        else:
            assert query.trace == ["finish"]


@pytest.mark.parametrize("sliced", [False, True])
def test_real_tlc_matches_native_multi_root_failure(entry, sliced):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    native = validate(entry, sliced=sliced)
    fallback = validate(entry, sliced=sliced, max_states=1, tlc=True, tlc_timeout=30)
    [query] = fallback.query_results
    assert query.backend == "tlc", [f.message for f in query.findings]
    assert native.query_results[0].status == query.status == "FAIL"
    trace = trace_query(entry, "done", sliced=sliced, max_states=1, tlc=True, tlc_timeout=30)
    assert trace["status"] == "FAIL" and trace["action_trace"] is None
    assert "init #2" in trace["message"] and "enabled=False" in trace["message"]


@pytest.mark.parametrize("sliced", [False, True])
def test_real_tlc_proves_converging_paths_from_all_roots(sliced):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))

    class Counter(Entity):
        n: int = Field(0, ge=0, le=3)

    tick = Action(id="tick", pre=[Counter.n < 3], effect=[Add(Counter.n, 1)])
    query = Reachable(Counter.n == 3, id="done", given_any=[[Counter(n=0)], [Counter(n=2)]])
    spec = Spec(id="merge", name="Merge", actions=[tick], queries=[query])
    result = validate_spec(spec, sliced=sliced, max_states=1, tlc=True, tlc_timeout=30)
    [checked] = result.query_results
    assert checked.status == "PASS" and checked.backend == "tlc"
    assert checked.trace == ["tick", "tick", "tick"]
    assert any("all 2 initial states" in f.message for f in checked.findings)


def test_mcp_uses_same_root_verdict_and_trace(entry):
    from analint.mcp_server import check_spec, trace_spec

    result = check_spec(str(entry))
    assert result["verdict"] == "FAIL"
    trace = trace_spec(str(entry), "done")
    assert trace["status"] == "FAIL" and trace["root"]["index"] == 2
    assert trace["final_state"]["Box.enabled"] is False
