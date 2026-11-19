"""Illegal roots must not be presented as ordinary missing-path evidence."""

import json
import zlib

import pytest

from analint import Action, Entity, Initial, Invariant, Not, Reachable, Set, Spec
from analint.reporter.base import Code
from analint.validator.engine import validate_spec


def model(source, legal_missing=False, single=False, matching=False):
    class Box(Entity):
        allowed: bool = True
        enabled: bool = True
        done: bool = False

    finish = Action(id="finish", pre=[Box.allowed, Box.enabled], effect=[Set(Box.done, True)])
    legal = Invariant(Box.allowed, id="legal")
    query = Reachable(Box.done, id="done")
    spec = Spec(id="roots", name="Roots", actions=[finish], invariants=[legal], queries=[query])
    roots = [[Box(allowed=False, done=matching)]]
    if not single:
        roots.append([Box()])
    if legal_missing:
        roots.append([Box(enabled=False)])
    if source in ("canonical", "initial"):
        relation = (
            Initial(given=roots[0])
            if single
            else Initial(
                vary=[Box.allowed, Box.enabled] if legal_missing else [Box.allowed],
                given=[Box(done=matching)],
            )
        )
        if source == "canonical":
            spec.initial = relation
        else:
            query.initial = relation
    else:
        query.given_any = roots
    return spec, query, Box


@pytest.mark.parametrize("matching", [False, True])
@pytest.mark.parametrize("source", ["canonical", "initial", "given_any"])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_invalid_root_is_explained_without_missing_path_claim(
    source, sliced, selected, tmp_path, monkeypatch, matching
):
    spec, _, _ = model(source, matching=matching)
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
@pytest.mark.parametrize("matching", [False, True])
def test_tlc_clarifies_invalid_roots_and_keeps_legal_failure(
    sliced, selected, legal_missing, matching
):
    from analint.backends.tlc import TlcUnavailable, find_tlc

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    spec, _, _ = model("given_any", legal_missing=legal_missing, matching=matching)
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
    assert len(calls) == 1  # the invalid root never launches TLC
    assert result.status == "FAIL"
    assert any(f.code == Code.QUERY_INVALID_ROOT for f in result.findings)
    expected = Code.TLC_FAILED if later == "error" else Code.TLC_TRANSITION_DEFECT
    assert any(f.code == expected for f in result.findings)


@pytest.fixture(params=[False, True])
def matching(request):
    return request.param


@pytest.fixture
def entry(tmp_path, matching):
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
    if matching:
        path.write_text(path.read_text().replace("done: bool = False", "done: bool = True"))
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


@pytest.mark.parametrize("source", ["given", "given_any", "initial", "canonical"])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_invalid_matching_root_never_supplies_positive_witness(source, sliced, selected):
    spec, query, box = model(source, single=True, matching=True)
    if source == "given":
        query.given_any = []
        query.given = [box(allowed=False, done=True)]
    result = validate_spec(spec, sliced=sliced, checks=["done"] if selected else None)
    assert result.verdict == "FAIL"
    [qr] = result.query_results
    assert qr.status == "FAIL"
    assert any(f.code == Code.QUERY_INVALID_ROOT for f in qr.findings)
    assert not any(f.code == Code.WITNESS for f in qr.findings)


@pytest.mark.parametrize("sliced", [False, True])
def test_matching_invalid_root_does_not_hide_a_legal_missing_path(sliced):
    spec, query, box = model("given_any", legal_missing=True, matching=True)
    query.given_any.insert(1, [box(allowed=False, done=True)])  # preserve original numbering
    result = validate_spec(spec, sliced=sliced)
    [qr] = result.query_results
    assert qr.status == "FAIL"
    assert any(f.code == Code.NOT_REACHABLE and "init #4" in f.message for f in qr.findings)
    assert not any(f.code == Code.WITNESS for f in qr.findings)


def test_invalid_matching_root_does_not_hide_predicate_errors():
    spec, query, box = model("given_any", single=True, matching=True)
    query.predicate = box.done < "wrong type"
    result = validate_spec(spec)
    assert result.verdict == "FAIL"
    assert any(f.code == Code.QUERY_EVALUATION_ERROR for f in result.query_results[0].findings)


@pytest.mark.parametrize("sliced", [False, True])
def test_invalid_matching_roots_under_budget_are_not_positive_witnesses(sliced):
    spec, _, _ = model("given_any", matching=True)
    result = validate_spec(spec, sliced=sliced, max_states=1)
    assert result.verdict == "FAIL"
    assert result.query_results[0].status == "INCONCLUSIVE"
    assert not any(f.code == Code.WITNESS for f in result.query_results[0].findings)


@pytest.mark.parametrize("mode", ["sliced", "whole", "unsliced"])
@pytest.mark.parametrize("matching", [False, True])
@pytest.mark.parametrize("legal_missing", [False, True])
def test_tlc_reuses_projected_legality_and_runs_only_legal_roots(
    monkeypatch, mode, matching, legal_missing
):
    from analint.backends.tlc import TlcResult
    from analint.reporter.base import QueryResult
    from analint.validator import slicing, tlc_fallback
    from analint.validator.explorer import resolve_query_initials

    spec, query, _ = model("given_any", matching=matching, legal_missing=legal_missing)
    query.given_any += query.given_any[:2]  # duplicate roots must not add launches
    roots, _ = resolve_query_initials(query, spec)
    analysis = None if mode == "unsliced" else slicing.SliceAnalysis(spec)
    piece = None
    if analysis is not None:
        piece = (
            analysis.whole
            if mode == "whole"
            else analysis.predicate_slice(query.predicate, canonical=False)
        )
        analysis.project_roots(piece, roots)  # the native pipeline already did this

        def recomputed(*args):
            pytest.fail("projected root legality was evaluated a second time")

        monkeypatch.setattr(slicing, "check_invariants", recomputed)
        monkeypatch.setattr(tlc_fallback, "check_invariants", recomputed)
    calls = []

    def run(export, **kwargs):
        calls.append(export)
        return TlcResult(
            "ok" if legal_missing and len(calls) == 2 else "violation",
            distinct_states=2,
            trace=["finish"],
        )

    monkeypatch.setattr(tlc_fallback, "run_tlc", run)
    result = QueryResult(query_id=query.id, kind="Reachable", status="INCONCLUSIVE")
    tlc_fallback._decide_query(spec, result, query, piece, analysis, roots, None)
    assert result.status == "FAIL" and result.backend == "tlc"
    assert len(calls) == (2 if legal_missing else 1)
    assert sum(f.code == Code.TLC_DECIDED for f in result.findings) == len(calls)
    assert result.states_explored == 1 + 2 * len(calls)  # includes the locally assessed root
    expected = Code.NOT_REACHABLE if legal_missing else Code.QUERY_INVALID_ROOT
    number = 3 if legal_missing else 1
    assert any(f.code == expected and f"init #{number}" in f.message for f in result.findings)
    assert not any(f.code == Code.WITNESS for f in result.findings)


@pytest.mark.parametrize("predicate", ["matches", "misses", "error", "missing", "unknown"])
def test_inert_root_is_decided_locally_without_hiding_predicate_problems(monkeypatch, predicate):
    from analint import Event
    from analint.reporter.base import QueryResult
    from analint.validator import tlc_fallback
    from analint.validator.explorer import resolve_query_initials

    spec, query, box = model("given_any", single=True, matching=predicate == "matches")
    expected = Code.QUERY_INVALID_ROOT
    if predicate == "error":
        query.predicate = box.done < "wrong type"
        expected = Code.QUERY_EVALUATION_ERROR
    elif predicate == "missing":

        class Payload(Event):
            ready: bool = True

        query.predicate = Payload.ready == True  # noqa: E712 - symbolic DSL comparison
        expected = Code.QUERY_VACUOUS
    elif predicate == "unknown":
        query.predicate = object()
        expected = Code.QUERY_EVALUATION_ERROR

    def launched(*args, **kwargs):
        pytest.fail("TLC launched for a root with no possible successors")

    monkeypatch.setattr(tlc_fallback, "run_tlc", launched)
    roots, _ = resolve_query_initials(query, spec)
    result = QueryResult(query_id=query.id, kind="Reachable", status="INCONCLUSIVE")
    tlc_fallback._decide_query(spec, result, query, None, None, roots, None)
    assert result.status == "FAIL" and result.backend is None
    assert any(f.code == expected for f in result.findings)
    assert not any(f.code in {Code.TLC_DECIDED, Code.WITNESS} for f in result.findings)
