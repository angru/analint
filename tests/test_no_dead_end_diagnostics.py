"""Explain invariant-invalid witnesses without changing recoverability semantics."""

import json

import pytest
from typer.testing import CliRunner

from analint import Action, Entity, Invariant, NoDeadEnd, Not, Or, Set, Spec
from analint.cli import app
from analint.mcp_server import check_spec, trace_spec
from analint.reporter.base import Code, Finding, Severity
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import prepare_model, validate, validate_spec
from analint.validator.exploration_service import trace_query
from analint.validator.explorer import _eval_no_dead_end, build_canonical_initials, explore
from analint.validator.kernel import Outcome, step

SPEC = """from analint import Action, And, Entity, Invariant, NoDeadEnd, Not, Set, Spec

class Account(Entity):
    disabled: bool = False
    has_position: bool = False

disable = Action(pre=[Not(Account.disabled), Not(Account.has_position)],
                 effect=[Set(Account.disabled, True)])
open_position = Action(pre=[Not(Account.has_position)], effect=[Set(Account.has_position, True)])
close_position = Action(pre=[Account.has_position], effect=[Set(Account.has_position, False)])
disabled_is_flat = Invariant(Not(And(Account.disabled, Account.has_position)))
can_go_flat = NoDeadEnd(goal=Not(Account.has_position))
spec = Spec(id="f13", name="F13", actions=[disable, open_position, close_position],
            invariants=[disabled_is_flat], queries=[can_go_flat])
"""


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(SPEC)
    return path


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_invalid_successor_has_its_own_diagnostic(entry, sliced, selected):
    spec = prepare_model(entry).spec
    result = validate_spec(spec, sliced=sliced, checks=["can_go_flat"] if selected else None)
    [qr] = result.query_results
    assert result.verdict == qr.status == "FAIL"
    assert qr.trace == ["disable", "open_position"]
    [finding] = [f for f in qr.findings if f.severity is Severity.ERROR]
    assert finding.code == "query.invalid_state"
    assert "disabled_is_flat" in finding.message and "not expanded" in finding.message
    assert "can no longer be reached" not in finding.message
    assert qr.states_explored == 4
    account = spec.entities[0]
    ctx = {account: account(disabled=True, has_position=True)}
    assert step(spec, spec.actions[2], ctx).outcome is Outcome.ACCEPTED
    # The separate invariant failure must remain visible in full/selected reports.
    assert any(f.code is Code.INVARIANT_VIOLATED for f in result.exploration_findings)


def test_reports_cache_and_trace_preserve_the_explanation(entry, monkeypatch):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    fresh = stable(result_to_dict(validate(entry, checks=["can_go_flat"])))
    fresh["selection"]["options"]["cache"] = True
    cold = stable(result_to_dict(validate(entry, checks=["can_go_flat"], cache=True)))
    assert cold == fresh

    def miss(*args, **kwargs):
        pytest.fail("expected warm cache including finding-to-state provenance")

    monkeypatch.setattr("analint.validator.explorer._explore", miss)
    assert stable(result_to_dict(validate(entry, checks=["can_go_flat"], cache=True))) == cold
    for compact in (False, True):
        args = ["check", str(entry), "--check", "can_go_flat", "--cache", "-f", "json"]
        if compact:
            args.append("--compact")
        cli = CliRunner().invoke(app, args)
        assert cli.exit_code == 1, cli.output
        report = json.loads(cli.output)
        assert "query.invalid_state" in cli.output
        assert stable(report) == stable(
            check_spec(str(entry), checks=["can_go_flat"], cache=True, compact=compact)
        )
    terminal = CliRunner().invoke(app, ["check", str(entry), "--check", "can_go_flat", "--cache"])
    assert terminal.exit_code == 1 and "not expanded" in terminal.output
    trace = trace_query(entry, "can_go_flat", cache=True)
    assert trace == trace_spec(str(entry), "can_go_flat", cache=True)
    assert "not expanded" in trace["message"]
    assert "disabled_is_flat" in trace["message"]
    terminal_trace = CliRunner().invoke(app, ["trace", "can_go_flat", "-p", str(entry), "--cache"])
    assert "not expanded" in terminal_trace.output


def test_provenance_not_message_or_location_identifies_invalid_witness(entry):
    spec = prepare_model(entry).spec
    roots, _ = build_canonical_initials(spec)
    exp = explore(spec, roots, 100)
    [original] = [i for i, f in enumerate(exp.findings) if f.code is Code.INVARIANT_VIOLATED]
    witness = _eval_no_dead_end(spec.queries[0], "can_go_flat", exp).witness_key
    index = exp.index[witness]
    exp.findings[original].message = "unrelated prose without trace or invariant name"
    assert (
        _eval_no_dead_end(spec.queries[0], "can_go_flat", exp).findings[0].code
        == "query.invalid_state"
    )
    exp.finding_states[original] = {0}  # same finding, another state's provenance
    qr = _eval_no_dead_end(spec.queries[0], "can_go_flat", exp)
    assert qr.findings[0].code is Code.DEAD_END
    assert "can no longer be reached" in qr.findings[0].message
    exp.finding_states.clear()
    assert _eval_no_dead_end(spec.queries[0], "can_go_flat", exp).findings[0].code is Code.DEAD_END
    # A transition diagnostic with a matching location/state is not an invariant failure.
    exp.findings = [
        Finding(Severity.ERROR, "invariant:disabled_is_flat", "breaks", Code.EVALUATION_ERROR)
    ]
    exp.finding_states = {0: {index}}
    assert _eval_no_dead_end(spec.queries[0], "can_go_flat", exp).findings[0].code is Code.DEAD_END


def test_legal_dead_end_and_unreachable_goal_keep_their_diagnostics():
    class Box(Entity):
        stuck: bool = False

    lock = Action(id="lock", effect=[Set(Box.stuck, True)])
    query = NoDeadEnd(Not(Box.stuck), id="recover")
    spec = Spec(id="s", name="S", actions=[lock], queries=[query])
    qr = validate_spec(spec).query_results[0]
    assert qr.status == "FAIL" and qr.trace == ["lock"]
    assert qr.findings[0].code is Code.DEAD_END
    assert "can no longer be reached" in qr.findings[0].message
    query.goal = Box.stuck == "impossible"
    assert validate_spec(spec).query_results[0].findings[0].code is Code.GOAL_UNREACHABLE


@pytest.mark.parametrize("tlc", [False, True])
def test_budget_does_not_claim_an_invalid_dead_end(entry, tlc):
    result = validate(entry, max_states=1, tlc=tlc)
    qr = result.query_results[0]
    assert qr.status == "INCONCLUSIVE"
    assert not any(f.code == "query.invalid_state" for f in qr.findings)


@pytest.mark.parametrize("sliced", [False, True])
def test_violation_and_evaluation_error_are_distinguished(entry, sliced):
    spec = prepare_model(entry).spec
    account = spec.entities[0]
    spec.invariants.append(
        Invariant(
            Or(Not(account.disabled), Not(account.has_position), account.has_position < "invalid"),
            id="broken_predicate",
        )
    )
    result = validate_spec(spec, sliced=sliced)
    qr = result.query_results[0]
    assert qr.status == result.verdict == "FAIL"
    assert qr.findings[0].code == "query.invalid_state"
    assert "violated: 'disabled_is_flat'" in qr.findings[0].message
    assert "evaluation failed: 'broken_predicate'" in qr.findings[0].message
    assert {Code.INVARIANT_VIOLATED, Code.INVARIANT_EVALUATION_ERROR} <= {
        f.code for f in result.exploration_findings
    }


def test_coalesced_error_provenance_applies_to_each_origin(tmp_path):
    from analint.validator.exploration_cache import use_store

    class Box(Entity):
        ok: bool = True
        mark: bool = False

    inv = Invariant(Or(Box.ok, Box.ok < "invalid"), id="broken")
    query = NoDeadEnd(Not(Box.mark), id="recover")
    spec = Spec(id="s", name="S", invariants=[inv], queries=[query])
    roots = [{Box: Box(ok=False)}, {Box: Box(ok=False, mark=True)}, {Box: Box()}]
    with use_store(tmp_path):
        cold = explore(spec, roots, 100)
        warm = explore(spec, roots, 100)
    for exp in (cold, warm):
        assert len(exp.findings) == 1
        assert exp.finding_states == {0: {0, 1}}
        for goal, origin in ((Not(Box.mark), 1), (Box.mark == True, 0)):  # noqa: E712
            query.goal = goal
            qr = _eval_no_dead_end(query, query.id, exp)
            assert qr.findings[0].code == "query.invalid_state"
            assert exp.index[qr.witness_key] == origin
            assert "evaluation failed: 'broken'" in qr.findings[0].message


@pytest.mark.parametrize("sliced", [False, True])
def test_legal_first_witness_is_not_blame_shifted_to_an_invalid_successor(sliced):
    class Box(Entity):
        stuck: bool = False
        invalid: bool = False

    break_it = Action(id="break", effect=[Set(Box.stuck, True), Set(Box.invalid, True)])
    legal = Invariant(Not(Box.invalid), id="legal")
    query = NoDeadEnd(Not(Box.stuck), id="recover", given_any=[[Box(stuck=True)], [Box()]])
    spec = Spec(id="s", name="S", actions=[break_it], invariants=[legal], queries=[query])
    result = validate_spec(spec, sliced=sliced)
    qr = result.query_results[0]
    assert qr.status == "FAIL" and qr.trace == []
    assert qr.findings[0].code is Code.DEAD_END
    assert "init #1" in qr.findings[0].message
    assert any(f.code is Code.INVARIANT_VIOLATED for f in result.exploration_findings)
