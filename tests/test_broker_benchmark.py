"""Broker increment intent gates; budgets are structural limits, not timing gates."""

from pathlib import Path

import pytest

from analint.reporter.base import Severity
from analint.validator.engine import prepare_model, validate

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "increment, entities, scenarios", [("m4", 7, 58), ("m5", 10, 72), ("m6", 12, 86)]
)
def test_increment_is_well_formed_and_its_witnesses_execute(increment, entities, scenarios):
    path = ROOT / "benchmarks" / "broker" / f"{increment}.py"
    prepared = prepare_model(path)
    assert not prepared.load_errors
    assert not prepared.structural_findings
    assert len(prepared.spec.entities) == entities
    assert len(prepared.spec.scenarios) == scenarios
    result = validate(path, max_states=100)
    assert all(s.passed for s in result.scenario_results)
    assert all(f.passed for f in result.flow_results)
    assert not any(f.severity == Severity.ERROR for f in result.exploration_findings)
    assert result.verdict == "INCONCLUSIVE"
    assert all(i.status != "NOT_CHECKED" for i in result.invariant_results)


def test_m6_capacities_change_the_root_without_mutating_m4():
    from benchmarks.broker.domain import Capacity

    from analint.validator.explorer import build_canonical_initials

    m4 = prepare_model(ROOT / "benchmarks/broker/m4.py").spec
    m6 = prepare_model(ROOT / "benchmarks/broker/m6.py").spec
    first, _ = build_canonical_initials(m4)
    last, _ = build_canonical_initials(m6)
    assert all(
        ctx[Capacity].accounts == ctx[Capacity].orders == ctx[Capacity].methods == 1
        for ctx in first
    )
    assert all(
        ctx[Capacity].accounts == ctx[Capacity].orders == ctx[Capacity].methods == 2 for ctx in last
    )


def test_worst_order_scenario_catches_a_missing_priority_guard():
    from benchmarks.broker.domain import Owner
    from benchmarks.broker.portfolio import (
        primary,
        sc_stop_out_cannot_choose_the_better_order,
        second,
    )
    from benchmarks.broker.risk import stop_worst_order

    from analint import Expect, Scenario
    from analint.validator.scenario_runner import run_scenario

    spec = prepare_model(ROOT / "benchmarks/broker/m6.py").spec
    original = stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=second)
    # bind() is memoized; keep the planted defect out of the shared model.
    broken = original.model_copy(update={"pre": original.pre[:-1]})
    broken._kernel_plan = None
    probe = Scenario(
        id="priority_probe",
        action=broken,
        given=sc_stop_out_cannot_choose_the_better_order.given,
        expected=Expect.FAIL,
    )
    assert not run_scenario(probe, spec).passed


@pytest.mark.parametrize("cent, expected", [(True, "FAIL"), (False, "PASS")])
def test_zero_equity_margin_threshold_depends_on_account_class(cent, expected):
    from benchmarks.broker.domain import Capacity, Equity, Margin, Owner
    from benchmarks.broker.risk import first, market_moves, primary, second, secondary
    from examples.broker.domain import AccountKind

    from analint import Absent, Expect, Scenario
    from analint.validator.scenario_runner import run_scenario

    spec = prepare_model(ROOT / "benchmarks/broker/m4.py").spec
    scenario = Scenario(
        id="threshold_probe",
        action=market_moves.bind(
            acct=primary, owner=Owner.PRIMARY, equity=Equity.ZERO, margin=Margin.CALL
        ),
        given=[
            Capacity(),
            primary(kind=AccountKind.CENT if cent else AccountKind.STANDARD),
            Absent(secondary),
            first(owner=Owner.PRIMARY),
            Absent(second),
        ],
        expected=Expect.FAIL if expected == "FAIL" else Expect.PASS,
    )
    assert run_scenario(scenario, spec).passed


def test_risk_increment_matches_the_tlc_cross_check():
    """research/34 §8 B2: TLC counts 54,084 distinct states for the M4 risk
    increment over three regions it never reads; one region is a third. A
    drift here means the kernel's presence/quantifier/Create-Delete semantics
    no longer match the cross-checked Quint port (benchmarks/broker/risk.qnt)."""
    from benchmarks.broker.domain import orders, risk_accounts
    from benchmarks.broker.risk import risk
    from examples.broker.domain import Client, Onboarding, Region

    from analint import Absent, Initial, Spec
    from analint.validator.explorer import build_canonical_initials, explore

    spec = Spec(
        id="risk_one_region",
        name="risk",
        imports=[risk],
        initial=Initial(
            vary=[Client.region],
            where=[Client.region == Region.STANDARD],
            given=[
                Client(onboarding=Onboarding.CONTACTS),
                *(Absent(slot) for slot in risk_accounts),
                *(Absent(slot) for slot in orders),
            ],
        ),
    )
    initials, error = build_canonical_initials(spec)
    assert initials, error
    exp = explore(spec, initials, 100_000)
    assert not exp.capped and not exp.findings
    assert len(exp.states) == 54_084 // 3
