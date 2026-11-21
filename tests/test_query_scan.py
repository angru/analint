"""Query scan work and compatibility with the full pre-optimization reports."""

import hashlib
import json
from pathlib import Path

import pytest

from analint import Action, Entity, Set, Spec, Unreachable
from analint.reporter.base import Code
from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer
from analint.validator.engine import validate, validate_spec

ROOT = Path(__file__).resolve().parents[1]
BASE_REPORTS = json.loads(
    (Path(__file__).with_name("snapshots") / "query_reports_fb04fc6.json").read_text()
)


def _report_digest(entry):
    path, _, extra = entry.partition(" + ")
    # Use the existing bounded differential budget for the 4.4M-state risk increment.
    budget = 2000 if path.endswith("/m6_risk.py") else None
    report = result_to_dict(
        validate(ROOT / path, max_states=budget, extra=ROOT / extra if extra else None)
    )
    for check in report["queries"] + report["invariants"]:
        check.pop("elapsed_ms", None)
    return hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()


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


@pytest.mark.parametrize("entry", BASE_REPORTS)
def test_query_optimization_preserves_base_json(entry):
    assert _report_digest(entry) == BASE_REPORTS[entry]
