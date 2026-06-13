"""Presence semantics for slots in a bounded Scope."""

import pytest

from analint import (
    Absent,
    Action,
    AlwaysHolds,
    Bound,
    Count,
    Entity,
    Exists,
    Expect,
    Field,
    ForAll,
    Max,
    Min,
    Param,
    Present,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Sum,
    Unreachable,
)
from analint.reporter.base import Severity
from analint.validator.explorer import run_query
from analint.validator.rule_checker import evaluate
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import _describe, validate_structural


class Account(Entity):
    balance: int = Field(0, ge=0, le=5)


accounts = Scope(Account, keys=["alice", "bob", "eve"], id="accounts")
alice = accounts["alice"]
bob = accounts["bob"]
eve = accounts["eve"]
account = Bound("account", accounts)


def _partial_context() -> dict:
    return {
        alice: alice(balance=1),
        bob: bob(balance=3),
        eve: Absent(eve),
    }


def test_present_checks_concrete_and_bound_instances():
    context = _partial_context()
    assert evaluate(Present(alice), context)
    assert not evaluate(Present(eve), context)
    assert evaluate(ForAll(account, Present(account)), context)
    assert evaluate(Exists(account, Present(account)), context)
    assert _describe(Present(eve)) == "PRESENT(Account['eve'])"


def test_quantifiers_and_aggregates_ignore_absent_slots():
    context = _partial_context()
    assert evaluate(ForAll(account, account.balance >= 0), context)
    assert evaluate(Count(account, account.balance > 0) == 2, context)
    assert evaluate(Sum(account, account.balance) == 4, context)
    assert evaluate(Min(account, account.balance) == 1, context)
    assert evaluate(Max(account, account.balance) == 3, context)


def test_empty_present_domain_has_explicit_finite_semantics():
    context = {
        alice: Absent(alice),
        bob: Absent(bob),
        eve: Absent(eve),
    }
    assert evaluate(ForAll(account, account.balance >= 0), context)
    assert not evaluate(Exists(account, account.balance >= 0), context)
    assert evaluate(Count(account, account.balance >= 0) == 0, context)
    assert evaluate(Sum(account, account.balance) == 0, context)
    with pytest.raises(ValueError, match="has no present instances"):
        evaluate(Min(account, account.balance) == 0, context)


def test_scenario_materializes_omitted_scope_slots_as_absent():
    audit = Action(id="audit", pre=[Count(account, account.balance >= 0) == 2])
    scenario = Scenario(
        id="audit_two",
        name="Audit two accounts",
        action=audit,
        given=[alice(balance=1), bob(balance=2)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[audit],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed
    warnings = [
        finding
        for finding in validate_structural(spec)
        if finding.severity == Severity.WARNING and "not in given" in finding.message
    ]
    assert not warnings


def test_present_composes_with_instance_params():
    target = Param("target", accounts)
    inspect = Action(
        id="inspect",
        params=[target],
        pre=[Present(target), target.balance >= 0],
    )
    scenario = Scenario(
        id="inspect_absent",
        name="Inspect absent",
        action=inspect.bind(target=eve),
        given=[alice(balance=1)],
        expected=Expect.FAIL,
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[inspect],
        scenarios=[scenario],
    )
    result = run_scenario(scenario, spec)
    assert result.passed
    assert not any("evaluation error" in finding.message for finding in result.findings)


def test_present_is_rejected_in_static_param_where():
    target = Param("target", accounts)
    inspect = Action(id="inspect", params=[target], where=[Present(target)])
    with pytest.raises(TypeError, match="cannot be used in where"):
        Spec(
            id="s",
            name="S",
            entities=[Account],
            scopes=[accounts],
            actions=[inspect],
        )


def test_modifying_an_absent_slot_is_blocked_before_effects():
    touch = Action(id="touch", effect=[Set(eve.balance, 1)])
    scenario = Scenario(
        id="touch_absent",
        name="Touch absent",
        action=touch,
        given=[Absent(eve)],
        expected=Expect.FAIL,
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[touch],
        scenarios=[scenario],
    )
    result = run_scenario(scenario, spec)
    assert result.passed
    assert any("cannot modify absent entity" in finding.message for finding in result.findings)


def test_explorer_tracks_presence_and_defaults_remain_present():
    partial = run_query(
        AlwaysHolds(
            Count(account, account.balance >= 0) == 2,
            given=[Absent(eve)],
            id="two_present",
        ),
        Spec(id="s", name="S", entities=[Account], scopes=[accounts]),
        cache={},
    )
    assert partial.status == "PASS"
    assert partial.states_explored == 1

    absent_stays_absent = run_query(
        Unreachable(
            Present(eve),
            given=[Absent(eve)],
            id="eve_is_absent",
        ),
        Spec(id="s", name="S", entities=[Account], scopes=[accounts]),
        cache={},
    )
    assert absent_stays_absent.status == "PASS"

    present_required = run_query(
        AlwaysHolds(
            Present(eve),
            given=[Absent(eve)],
            id="eve_must_exist",
        ),
        Spec(id="s", name="S", entities=[Account], scopes=[accounts]),
        cache={},
    )
    assert present_required.status == "FAIL"
    assert "@present=False" in present_required.findings[0].message

    default = run_query(
        Reachable(
            Count(account, account.balance >= 0) == 3,
            id="all_present_by_default",
        ),
        Spec(id="s", name="S", entities=[Account], scopes=[accounts]),
        cache={},
    )
    assert default.status == "PASS"


def test_presence_targets_are_structurally_validated():
    unbound = Action(id="unbound", pre=[Present(account)])
    other_accounts = Scope(Account, keys=["mallory"], id="other_accounts")
    unregistered = Action(id="unregistered", pre=[Present(other_accounts["mallory"])])
    misplaced = Action(id="misplaced", where=[Present(alice)])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[unbound, unregistered, misplaced],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("outside a quantifier" in finding.message for finding in errors)
    assert any("not registered in spec.scopes" in finding.message for finding in errors)
    assert any("where= only filters parameterized" in finding.message for finding in errors)
