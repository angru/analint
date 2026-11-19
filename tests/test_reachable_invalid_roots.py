"""Illegal roots must not be presented as ordinary missing-path evidence."""

import json
import zlib

import pytest

from analint import Action, Entity, Initial, Invariant, Not, Reachable, Set, Spec
from analint.reporter.base import Code
from analint.validator.engine import validate_spec


def model(source, legal_missing=False, single=False):
    class Box(Entity):
        allowed: bool = True
        enabled: bool = True
        done: bool = False

    finish = Action(id="finish", pre=[Box.allowed, Box.enabled], effect=[Set(Box.done, True)])
    legal = Invariant(Box.allowed, id="legal")
    query = Reachable(Box.done, id="done")
    spec = Spec(id="roots", name="Roots", actions=[finish], invariants=[legal], queries=[query])
    roots = [[Box(allowed=False)]]
    if not single:
        roots.append([Box()])
    if legal_missing:
        roots.append([Box(enabled=False)])
    if source in ("canonical", "initial"):
        relation = (
            Initial(given=roots[0])
            if single
            else Initial(vary=[Box.allowed, Box.enabled] if legal_missing else [Box.allowed])
        )
        if source == "canonical":
            spec.initial = relation
        else:
            query.initial = relation
    else:
        query.given_any = roots
    return spec, query, Box


@pytest.mark.parametrize("source", ["canonical", "initial", "given_any"])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_invalid_root_is_explained_without_missing_path_claim(
    source, sliced, selected, tmp_path, monkeypatch
):
    spec, _, _ = model(source)
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    findings = []
    for cache in [False, True, True]:
        result = validate_spec(
            spec, sliced=sliced, checks=["done"] if selected else None, cache=cache
        )
        assert result.verdict == "FAIL"
        [qr] = result.query_results
        assert qr.status == "FAIL"
        assert any(f.code == Code.QUERY_INVALID_ROOT for f in qr.findings)
        assert not any(f.code == Code.NOT_REACHABLE for f in qr.findings)
        findings.append([(f.code, f.message) for f in qr.findings])
    assert findings[0] == findings[1] == findings[2]


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_legal_missing_root_remains_a_missing_path(sliced, selected):
    spec, _, _ = model("given_any", legal_missing=True)
    result = validate_spec(spec, sliced=sliced, checks=["done"] if selected else None)
    assert result.verdict == "FAIL"
    qr = result.query_results[0]
    assert any(f.code == Code.NOT_REACHABLE and "init #3" in f.message for f in qr.findings)


@pytest.mark.parametrize("sliced", [False, True])
def test_single_invalid_root_remains_fail(sliced):
    spec, _, _ = model("given_any", single=True)
    result = validate_spec(spec, sliced=sliced, checks=["done"])
    assert result.verdict == "FAIL"
    assert any(f.code == "query.invalid_root" for f in result.query_results[0].findings)


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("legal_missing", [False, True])
def test_tlc_clarifies_invalid_roots_and_keeps_legal_failure(sliced, selected, legal_missing):
    from analint.backends.tlc import TlcUnavailable, find_tlc

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    spec, _, _ = model("given_any", legal_missing=legal_missing)
    result = validate_spec(
        spec, sliced=sliced, checks=["done"] if selected else None, max_states=1, tlc=True
    )
    assert result.verdict == "FAIL"
    qr = result.query_results[0]
    assert qr.status == "FAIL" and qr.backend == "tlc"
    if legal_missing:
        assert any(f.code == Code.NOT_REACHABLE and "init #3" in f.message for f in qr.findings)
    else:
        assert any(
            f.code == Code.QUERY_INVALID_ROOT and "init #1" in f.message for f in qr.findings
        )
        assert not any(f.code == Code.NOT_REACHABLE for f in qr.findings)


def test_projection_chooses_legal_representative_without_discarding_root_error():
    spec, query, box = model("given_any")
    spec.actions[0].pre = [Not(Not(box.enabled))]  # allowed is outside the property slice
    query.given_any += [query.given_any[0], query.given_any[1]]
    result = validate_spec(spec, sliced=True, checks=["done"])
    assert result.verdict == "FAIL"
    assert result.query_results[0].status == "PASS"
    assert any(f.code == Code.INVARIANT_VIOLATED for f in result.exploration_findings)


def test_unknown_root_provenance_keeps_original_diagnostic():
    from analint.validator.explorer import _eval_reachable, explore, resolve_query_initials

    spec, query, _ = model("given_any")
    roots, _ = resolve_query_initials(query, spec)
    graph = explore(spec, roots, 100)
    assert graph.invalid_roots == {0}
    graph.invalid_roots.clear()  # no explicit attribution: do not infer from prose
    result = _eval_reachable(query, query.id, graph, True)
    assert any(f.code == Code.NOT_REACHABLE and "init #1" in f.message for f in result.findings)


@pytest.mark.parametrize("later", ["error", "defect"])
def test_tlc_keeps_known_invalid_failure_and_later_backend_diagnostic(monkeypatch, later):
    from analint.backends.tlc import TlcResult
    from analint.validator import tlc_fallback

    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: ("java", "test.jar"))
    calls = []

    def run(export, **kwargs):
        calls.append(export)
        if len(calls) == 1:
            return TlcResult("ok", distinct_states=1)
        if later == "defect":
            action = next(iter(export.actions))
            return TlcResult("violation", violated=f"NoDefect_{action}", distinct_states=1)
        return TlcResult("error", output="Error: backend stopped")

    monkeypatch.setattr(tlc_fallback, "run_tlc", run)
    spec, query, _ = model("given_any")
    from analint.reporter.base import QueryResult
    from analint.validator.explorer import resolve_query_initials

    roots, _ = resolve_query_initials(query, spec)
    result = QueryResult(query_id=query.id, kind="Reachable", status="INCONCLUSIVE")
    tlc_fallback._decide_query(spec, result, query, None, None, roots, None)
    assert result.status == "FAIL"
    assert any(f.code == Code.QUERY_INVALID_ROOT for f in result.findings)
    expected = Code.TLC_FAILED if later == "error" else Code.TLC_TRANSITION_DEFECT
    assert any(f.code == expected for f in result.findings)


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text("""from analint import Action, Entity, Initial, Invariant, Reachable, Set, Spec
class Box(Entity):
    allowed: bool = True
    done: bool = False
finish = Action(pre=[Box.allowed], effect=[Set(Box.done, True)])
legal = Invariant(Box.allowed)
done = Reachable(Box.done)
spec = Spec(id="roots", name="Roots", actions=[finish], invariants=[legal],
            queries=[done], initial=Initial(vary=[Box.allowed]))
""")
    return path


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_cli_check_preserves_exit_one_and_trace_explains_root(entry, sliced, selected):
    from typer.testing import CliRunner

    from analint.cli import app

    runner = CliRunner()
    options = [] if sliced else ["--no-slice"]
    check = runner.invoke(
        app,
        ["check", str(entry), "-f", "json", *options, *(["--check", "done"] if selected else [])],
    )
    assert check.exit_code == 1, check.output
    report = json.loads(check.output)
    assert report["verdict"] == "FAIL"
    assert any(f["code"] == "query.invalid_root" for f in report["queries"][0]["findings"])
    trace = runner.invoke(app, ["trace", "done", "-p", str(entry), "-f", "json", *options])
    assert trace.exit_code == 0, trace.output  # trace is an inspection command
    payload = json.loads(trace.output)
    assert payload["status"] == payload["verification_verdict"] == "FAIL"
    assert payload["root"]["index"] == 1
    assert payload["steps"] == []
    assert payload["final_state"]["Box.allowed"] is False
    assert "invalid" in payload["message"] and "not expanded" in payload["message"]
    terminal = runner.invoke(app, ["trace", "done", "-p", str(entry), *options])
    assert "invalid" in terminal.output and "not expanded" in terminal.output


def test_tlc_trace_preserves_invalid_root_explanation(entry):
    from analint.backends.tlc import TlcUnavailable, find_tlc
    from analint.validator.exploration_service import trace_query

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    payload = trace_query(entry, "done", max_states=1, tlc=True)
    assert payload["backend"] == "tlc"
    assert payload["status"] == payload["verification_verdict"] == "FAIL"
    assert payload["root"] is None and payload["final_state"] == {}
    assert "init #1 is invalid" in payload["message"]


@pytest.mark.parametrize("damage", [None, "missing", "not_a_root"])
def test_disk_cache_retains_root_provenance_and_rejects_invalid_metadata(
    entry, tmp_path, monkeypatch, damage
):
    from analint.validator import explorer
    from analint.validator.engine import validate

    directory = tmp_path / "cache"
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(directory))

    def report():
        result = validate(entry, checks=["done"], cache=True)
        return result.verdict, [(f.code, f.message) for f in result.query_results[0].findings]

    cold = report()
    paths = list(directory.glob("*.json.z"))
    assert paths
    if damage:
        for path in paths:
            data = json.loads(zlib.decompress(path.read_bytes()))
            if damage == "missing":
                del data["invalid_roots"]
            else:
                data["invalid_roots"] = [999]
            path.write_bytes(zlib.compress(json.dumps(data).encode()))
    calls = []
    explore = explorer._explore

    def record(*args, **kwargs):
        calls.append(1)
        return explore(*args, **kwargs)

    monkeypatch.setattr(explorer, "_explore", record)
    assert report() == cold
    assert bool(calls) == bool(damage)


def test_invariant_evaluation_error_is_also_an_unexpanded_root():
    spec, _, box = model("given_any", single=True)
    spec.invariants[0].expression = box.allowed < "wrong type"
    result = validate_spec(spec, checks=["done"])
    assert result.verdict == "FAIL"
    assert any(f.code == Code.QUERY_INVALID_ROOT for f in result.query_results[0].findings)
    assert any(f.code == Code.INVARIANT_EVALUATION_ERROR for f in result.exploration_findings)


def test_invalid_root_already_matching_goal_keeps_query_status_and_overall_fail():
    spec, query, box = model("given_any", single=True)
    query.given_any = [[box(allowed=False, done=True)]]
    result = validate_spec(spec, checks=["done"])
    assert result.verdict == "FAIL"
    assert result.query_results[0].status == "PASS"  # preserve existing query semantics
    assert not any(f.code == Code.QUERY_INVALID_ROOT for f in result.query_results[0].findings)
