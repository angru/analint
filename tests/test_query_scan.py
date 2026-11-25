"""Query scan work and compatibility with the full pre-optimization reports."""

from pathlib import Path

import pytest

from analint import (
    Absent,
    Action,
    And,
    Bound,
    Entity,
    Exists,
    Present,
    Scope,
    Set,
    Spec,
    Unreachable,
)
from analint.reporter.base import Code
from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer
from analint.validator.engine import validate, validate_spec

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
REPORT_TARGETS = [
    *((path, None) for path in sorted((ROOT / "examples").glob("*/spec.py"))),
    *((path, None) for path in sorted((BENCHMARKS / "broker").glob("m*.py"))),
    *(
        (path, None)
        for path in sorted(BENCHMARKS.glob("*.py"))
        if path.name != "__init__.py" and not path.name.startswith("fulfillment_")
    ),
    *(
        (ROOT / "examples/fulfillment/spec.py", extra)
        for extra in sorted(BENCHMARKS.glob("fulfillment_*.py"))
    ),
]

LARGE_SCAN_MODELS = {
    BENCHMARKS / "broker/m4.py",
    BENCHMARKS / "broker/m4_risk.py",
    BENCHMARKS / "broker/m5.py",
    BENCHMARKS / "broker/m6.py",
    BENCHMARKS / "broker/m6_profile_methods.py",
}


def _interpreted_scan(exp, predicate, *, collect_matches=False):
    """Reference scan using the applicability and evaluation loop from fb04fc6."""
    scan = explorer._Scan()
    refs = explorer._collect_field_refs(predicate)
    for idx, key in enumerate(exp.order):
        ctx = explorer.decode_state(key)
        if any(explorer.field_context_key(ref) not in ctx for ref in refs):
            continue
        scan.applicable += 1
        try:
            if explorer.evaluate(predicate, ctx):
                if collect_matches:
                    scan.matches.append(idx)
                if scan.first_match is None:
                    scan.first_match = key
        except Exception as exc:
            message = f"evaluation error: {exc} [at: {explorer._trace_str(exp.trace_to(key))}]"
            if message not in scan.errors:
                scan.errors.append(message)
    return scan


def test_query_owned_root_still_reports_transition_defects():
    class Account(Entity):
        gated: bool = False
        attempted: bool = False
        result: int = 0

    attempt = Action(
        id="attempt",
        name="Attempt",
        pre=[Account.gated],
        effect=[Set(Account.attempted, True)],
        post=[Account.attempted == False],  # noqa: E712
    )
    record = Action(id="record", pre=[Account.gated], effect=[Set(Account.result, 1)])
    canonical = Unreachable(Account.result == 2, id="canonical")
    owned = Unreachable(Account.result == 2, id="owned", given=[Account(gated=True)])
    spec = Spec(id="accounts", name="Accounts", actions=[attempt, record], queries=[canonical])
    assert validate_spec(spec).verdict == "PASS"

    spec.queries.append(owned)
    result = validate_spec(spec)
    assert result.verdict == "FAIL"
    assert [query.status for query in result.query_results] == ["PASS", "PASS"]
    probe = result.query_results[1].model["attempts"][0]
    assert probe["relation"] == "over-approx"
    assert probe["clean"] and probe["status"] == "PASS"
    [finding] = result.exploration_findings
    assert finding.code == Code.POSTCONDITION_VIOLATED
    assert finding.location == "action:attempt"


def test_query_scan_reuses_slot_decoding(monkeypatch):
    class Account(Entity):
        balance: int = 0

    class Other(Entity):
        value: int = 0

    graph = explorer.Exploration()
    graph.keys.extend(
        explorer.state_key({Account: Account(), Other: Other(value=i)}) for i in range(20)
    )
    decode = explorer.decode_state
    decoded = []

    def counted(key):
        decoded.append(key)
        return decode(key)

    monkeypatch.setattr(explorer, "decode_state", counted)
    scan = explorer._scan_states(graph, Account.balance == 0, collect_matches=True)
    assert set(scan.matches) == set(range(20))
    repeated = explorer._scan_states(graph, Account.balance < 0)
    assert repeated.applicable == 20 and repeated.first_match is None
    assert len(decoded) == 1


def test_query_scan_preserves_late_errors_and_escaped_codes(monkeypatch):
    class ZAccount(Entity):
        divisor: int = 1

    class Earlier(Entity):
        value: int = 0

    # Lower the escape threshold and vary an earlier slot so the queried
    # slot moves in the byte representation of the third key.
    layout_id, _ = explorer._state_layout((ZAccount, Earlier))
    escape = max(2, layout_id + 1)
    monkeypatch.setattr(explorer, "_ESCAPE", escape)
    for value in range(escape + 1):
        explorer._intern(layout_id, 0, (value,))
    graph = explorer.Exploration()
    for idx, (value, divisor) in enumerate([(0, 1), (1, 0), (escape, 0)]):
        key = explorer.state_key(
            {ZAccount: ZAccount(divisor=divisor), Earlier: Earlier(value=value)}
        )
        graph.add_state(key, idx - 1, graph.action_code(f"step_{idx}"))

    scan = explorer._scan_states(graph, 1 // ZAccount.divisor == 1)
    assert scan.first_match == graph.keys[0]
    assert len(scan.errors) == 2
    assert all("division" in error for error in scan.errors)
    assert "step_2" in scan.errors[-1]


def test_restricted_context_preserves_quantification_and_presence():
    class Account(Entity):
        balance: int = 0

    class Unrelated(Entity):
        value: int = 0

    accounts = Scope(Account, keys=["a", "b"])
    a, b = accounts["a"], accounts["b"]
    member = Bound("member", accounts)
    predicate = And(Present(a), Exists(member, member.balance > 0))
    graph = explorer.Exploration()
    for i, (first, second) in enumerate(
        [
            (a(balance=1), Absent(b)),
            (a(balance=0), b(balance=1)),
            (Absent(a), b(balance=1)),
            (a(balance=0), Absent(b)),
            (a(balance=0), b(balance=1)),
        ]
    ):
        graph.keys.append(explorer.state_key({a: first, b: second, Unrelated: Unrelated(value=i)}))

    expected = _interpreted_scan(graph, predicate, collect_matches=True)
    actual = explorer._scan_states(graph, predicate, collect_matches=True)
    assert actual == expected
    assert list(actual.matches) == [0, 1, 4]
    cache = graph._query_context_cache
    assert cache is not None
    assert len(cache[2]) == 4
    assert all(Unrelated not in ctx for ctx in cache[2].values())


@pytest.mark.parametrize(
    ("entry", "extra"),
    [
        pytest.param(
            path,
            extra,
            id=str((extra or path).relative_to(ROOT)),
            marks=pytest.mark.benchmark if path in LARGE_SCAN_MODELS else (),
        )
        for path, extra in REPORT_TARGETS
    ],
)
def test_query_optimization_preserves_base_json(entry, extra, monkeypatch):
    # The 4.4M-state risk increment uses the existing differential budget.
    budget = 2000 if entry.name == "m6_risk.py" else None

    def report():
        result = result_to_dict(validate(entry, max_states=budget, extra=extra))
        for check in result["queries"] + result["invariants"]:
            check.pop("elapsed_ms", None)
        return result

    actual = report()
    with monkeypatch.context() as reference:
        reference.setattr(explorer, "_scan_states", _interpreted_scan)
        expected = report()
    assert actual == expected
