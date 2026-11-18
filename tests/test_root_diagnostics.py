"""Root legality owns its duplicate diagnostic, but not later violations."""

import json

import pytest
from typer.testing import CliRunner

from analint import AlwaysHolds, Initial
from analint.cli import app
from analint.mcp_server import check_spec, trace_spec
from analint.reporter.base import Code
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import prepare_model, validate, validate_spec
from analint.validator.exploration_service import trace_query


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text("""from analint import *

class A(Entity):
    n: int = Field(0, ge=0, le=1)

class B(Entity):
    n: int = Field(0, ge=0, le=3)

advance_a = Action(pre=[A.n < 1], effect=[Add(A.n, 1)])
advance_b = Action(pre=[B.n < 3], effect=[Add(B.n, 1)])
limit = Invariant(B.n <= 1)
safe = AlwaysHolds(A.n <= 1, given=[B(n=3)])
spec = Spec(id="roots", name="Root diagnostics", entities=[A, B], actions=[advance_a, advance_b],
            invariants=[limit], queries=[safe])
""")
    return path


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


@pytest.mark.parametrize("roots", ["given", "given_any", "initial", "canonical"])
@pytest.mark.parametrize("error", [False, True])
@pytest.mark.parametrize("sliced", [False, True])
def test_root_failure_has_no_nonblocking_duplicate(entry, roots, error, sliced):
    spec = prepare_model(entry).spec.model_copy(deep=True)
    b = spec.entities[1]
    query = spec.queries[0]
    if error:
        spec.invariants[0].expression = b.n < "wrong type"
    if roots != "given":
        query.given = []
        if roots == "given_any":
            query.given_any = [[b(n=2)], [b(n=3)]]
        elif roots == "initial":
            query.initial = Initial(given=[b(n=3)])
        else:
            spec.initial = Initial(given=[b(n=3)])
    result = validate_spec(spec, checks=["safe"], sliced=sliced)
    code = Code.INVARIANT_EVALUATION_ERROR if error else Code.INVARIANT_VIOLATED
    assert result.verdict == result.effective_verdict(strict=True) == "FAIL"
    assert any(
        f.code == code and f.location == "invariant:limit" for f in result.exploration_findings
    )
    assert not any(f.location == "invariant:limit" for f in result.model_findings)


@pytest.mark.parametrize("roots", ["given_any", "separate_queries"])
def test_later_violation_from_a_legal_root_survives(entry, roots):
    spec = prepare_model(entry).spec.model_copy(deep=True)
    a, b = spec.entities
    if roots == "given_any":
        spec.queries[0].given = []
        spec.queries[0].given_any = [[b(n=3)], [b()]]
    else:
        spec.queries.append(AlwaysHolds(a.n <= 1, given=[b()], id="legal"))
    result = validate_spec(spec, checks=[q.id for q in spec.queries])
    assert result.verdict == "FAIL"
    violations = [f for f in result.model_findings if f.location == "invariant:limit"]
    assert len(violations) == 1
    assert "advance_b → advance_b" in violations[0].message


def test_root_diagnostics_across_reports_cache_and_trace(entry, monkeypatch):
    from analint.validator import explorer

    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    fresh = stable(result_to_dict(validate(entry, checks=["safe"])))
    assert fresh["verdict"] == "FAIL" and fresh["model_findings"] == []
    fresh["selection"]["options"]["cache"] = True
    cold = stable(result_to_dict(validate(entry, checks=["safe"], cache=True)))
    assert cold == fresh

    def miss(*args, **kwargs):
        pytest.fail("expected warm exploration cache")

    monkeypatch.setattr(explorer, "_explore", miss)
    assert stable(result_to_dict(validate(entry, checks=["safe"], cache=True))) == cold
    for compact in (False, True):
        args = ["check", str(entry), "--check", "safe", "--cache", "--strict", "-f", "json"]
        if compact:
            args.append("--compact")
        cli = CliRunner().invoke(app, args)
        assert cli.exit_code == 1, cli.output
        report = json.loads(cli.output)
        assert report["verdict"] == "FAIL" and report["model_findings"] == []
        assert stable(
            check_spec(str(entry), checks=["safe"], cache=True, compact=compact)
        ) == stable(report)
    terminal = CliRunner().invoke(app, ["check", str(entry), "--check", "safe", "--cache"])
    assert terminal.exit_code == 1
    assert "initial #1 failed" in terminal.output
    assert "no unrelated findings in the assessed coverage" in terminal.output
    trace = trace_query(entry, "safe", cache=True)
    assert trace["verification_verdict"] == "FAIL" and trace["model_findings"] == []
    assert trace == trace_spec(str(entry), "safe", cache=True)


@pytest.mark.parametrize("error", [False, True])
def test_provenance_survives_cache_in_a_new_process(entry, monkeypatch, error):
    import subprocess
    import sys

    if error:
        entry.write_text(entry.read_text().replace("B.n <= 1", 'B.n < "wrong type"'))
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    expected = stable(result_to_dict(validate(entry, checks=["safe"], cache=True)))
    script = """import json, sys
from pathlib import Path
from analint.validator import explorer
from analint.validator.engine import validate
from analint.reporter.json_reporter import result_to_dict
def miss(*args, **kwargs):
    raise AssertionError("warm cache missed in child process")
explorer._explore = miss
print(json.dumps(result_to_dict(validate(Path(sys.argv[1]), checks=["safe"], cache=True))))
"""
    output = subprocess.run(
        [sys.executable, "-c", script, str(entry)], check=True, capture_output=True, text=True
    )
    assert stable(json.loads(output.stdout)) == expected
    assert expected["model_findings"] == [] and expected["verdict"] == "FAIL"


def test_suppression_needs_all_states_to_be_known_illegal_roots(entry):
    from analint.reporter.base import ValidationResult
    from analint.validator.explorer import explore, state_key
    from analint.validator.selection import select_checks
    from analint.validator.verification_scope import VerificationScope

    spec = prepare_model(entry).spec.model_copy(deep=True)
    a, b = spec.entities
    spec.invariants[0].expression = b.n < "wrong type"
    roots = [{a: a(), b: b(n=2)}, {a: a(), b: b(n=3)}]
    graph = explore(spec, roots, 10)
    # Equal error messages coalesce in the explorer; both origins must survive.
    assert len(graph.findings) == 1 and graph.finding_states == {0: {0, 1}}
    selection = select_checks(spec, ["safe"], None, None)
    scope = VerificationScope(spec, selection, sliced=True)
    scope.register(roots[:1], ["query:safe"])
    root_key = tuple(state_key(ctx) for ctx in roots)
    scope.routes[root_key] = {"query:safe"}

    def collect():
        result = ValidationResult(spec_id=spec.id, spec_name=spec.name, selection=selection.scope)
        scope.collect(result, {(root_key, 10): graph}, None)
        return result

    assert collect().model_findings  # root #2 has no blocking representative yet
    scope.register(roots[1:], ["query:safe"])
    graph.findings[0].message = "An entirely different rendering of this failure"
    assert not collect().model_findings
    graph.finding_states.clear()
    assert collect().model_findings  # no provenance: keep the diagnostic


@pytest.mark.parametrize("damage", ["missing", "bad_finding", "bad_state", "empty"])
def test_invalid_cached_provenance_falls_back_to_fresh_exploration(entry, monkeypatch, damage):
    import zlib

    from analint.validator import explorer

    directory = entry.parent / "cache"
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(directory))
    cold = stable(result_to_dict(validate(entry, checks=["safe"], cache=True)))
    for path in directory.glob("*.json.z"):
        data = json.loads(zlib.decompress(path.read_bytes()))
        if damage == "missing":
            del data["finding_states"]
        elif damage == "bad_finding":
            data["finding_states"] = [[-1, [0]]]
        elif damage == "bad_state":
            data["finding_states"] = [[0, [-1]]]
        else:
            data["finding_states"] = [[0, []]]
        path.write_bytes(zlib.compress(json.dumps(data).encode()))
    calls = []
    run = explorer._explore

    def record(*args, **kwargs):
        calls.append(1)
        return run(*args, **kwargs)

    monkeypatch.setattr(explorer, "_explore", record)
    assert stable(result_to_dict(validate(entry, checks=["safe"], cache=True))) == cold
    assert calls


def test_matching_prose_does_not_hide_a_later_evaluation_error(entry):
    from analint import Action, Or, Set

    spec = prepare_model(entry).spec.model_copy(deep=True)
    a, b = spec.entities
    spec.invariants[0].expression = Or(b.n == 0, b.n < "wrong type")
    # An action id can match the human-readable root marker. Root and later
    # evaluation errors then have identical messages; their states still differ.
    spec.actions = [Action(id="(initial state)", pre=[b.n == 0], effect=[Set(b.n, 2)])]
    spec.queries = [AlwaysHolds(a.n <= 1, id="safe", given_any=[[b(n=3)], [b()]])]
    result = validate_spec(spec, checks=["safe"])
    assert result.verdict == "FAIL"
    assert len(result.model_findings) == 1
    assert result.model_findings[0].code == Code.INVARIANT_EVALUATION_ERROR


def test_only_selected_nonblocking_duplicates_are_removed(entry, monkeypatch):
    from analint.validator.verification_scope import VerificationScope

    # A query depending on the offending invariant keeps its exploration
    # attribution. Full runs also retain their existing reports.
    spec = prepare_model(entry).spec.model_copy(deep=True)
    spec.queries[0].predicate = spec.entities[1].n <= 3
    baseline = {}
    cases = ({}, {"sliced": False}, {"checks": ["safe"]}, {"checks": ["safe"], "sliced": False})
    for options in cases:
        key = repr(options)
        baseline[key] = stable(result_to_dict(validate_spec(spec, **options)))
    original = VerificationScope.register

    def without_provenance(self, initials, checks):
        original(self, initials, checks)
        self.root_defects.clear()

    monkeypatch.setattr(VerificationScope, "register", without_provenance)
    for options in cases:
        assert stable(result_to_dict(validate_spec(spec, **options))) == baseline[repr(options)]
