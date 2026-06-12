"""Finite quantifiers and aggregates over bounded Scope instances."""

import pytest

from analint import (
    Action,
    AlwaysHolds,
    Assert,
    Bound,
    Count,
    Entity,
    Exists,
    Field,
    ForAll,
    In,
    Invariant,
    Max,
    Min,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Sum,
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


def _context(alice_balance: int, bob_balance: int, eve_balance: int) -> dict:
    return {
        alice: alice(balance=alice_balance),
        bob: bob(balance=bob_balance),
        eve: eve(balance=eve_balance),
    }


def test_for_all_and_exists_evaluate_over_scope():
    context = _context(1, 2, 0)
    assert evaluate(ForAll(account, account.balance >= 0), context)
    assert not evaluate(ForAll(account, account.balance > 0), context)
    assert evaluate(Exists(account, account.balance == 2), context)
    assert not evaluate(Exists(account, account.balance > 4), context)
    assert evaluate(ForAll(account, In(account.balance, [0, 1, 2])), context)


def test_nested_quantifiers_keep_outer_binding():
    candidate = Bound("candidate", accounts)
    greatest_exists = Exists(
        candidate,
        ForAll(account, candidate.balance >= account.balance),
    )
    assert evaluate(greatest_exists, _context(1, 4, 2))


def test_count_sum_min_and_max_evaluate_over_scope():
    context = _context(1, 4, 2)
    assert evaluate(Count(account, account.balance > 1) == 2, context)
    assert evaluate(Sum(account, account.balance) == 7, context)
    assert evaluate(Min(account, account.balance) == 1, context)
    assert evaluate(Max(account, account.balance) == 4, context)
    assert evaluate(
        Sum(account, account.balance * 2) + Count(account, account.balance == 1) == 15, context
    )


def test_nested_aggregate_keeps_outer_binding():
    candidate = Bound("candidate", accounts)
    rank_sum = Sum(
        candidate,
        Count(account, account.balance <= candidate.balance),
    )
    assert evaluate(rank_sum == 6, _context(1, 4, 2))


def test_value_aggregates_reject_predicate_bodies():
    with pytest.raises(TypeError, match="use Count"):
        Sum(account, account.balance > 0)


def test_aggregate_is_readable_and_collects_all_scope_instances():
    predicate = Sum(account, account.balance) <= 10
    assert _describe(predicate) == "SUM account IN accounts: account.balance <= 10"

    action = Action(id="audit_total", pre=[predicate])
    scenario = Scenario(
        id="audit_total",
        name="Audit total",
        action=action,
        given=[alice(balance=1), bob(balance=2), eve(balance=3)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed
    warnings = [
        finding
        for finding in validate_structural(spec)
        if finding.severity == Severity.WARNING and "not in given" in finding.message
    ]
    assert not warnings


def test_aggregate_can_drive_an_effect():
    class Ledger(Entity):
        total: int = 0

    snapshot = Action(
        id="snapshot",
        effect=[Set(Ledger.total, Sum(account, account.balance))],
    )
    scenario = Scenario(
        id="snapshot_total",
        name="Snapshot total",
        action=snapshot,
        given=[alice(balance=1), bob(balance=2), eve(balance=3), Ledger()],
        then=[Assert(Ledger.total == 6)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account, Ledger],
        scopes=[accounts],
        actions=[snapshot],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed


def test_quantifier_is_readable_and_collects_all_scope_instances():
    predicate = ForAll(account, account.balance >= 0)
    assert _describe(predicate) == "FORALL account IN accounts: account.balance >= 0"

    action = Action(id="audit", pre=[predicate])
    scenario = Scenario(
        id="audit_all",
        name="Audit all",
        action=action,
        given=[alice(balance=1), bob(balance=2), eve(balance=3)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed
    warnings = [
        finding
        for finding in validate_structural(spec)
        if finding.severity == Severity.WARNING and "not in given" in finding.message
    ]
    assert not warnings


def test_quantifier_in_invariant_and_reachability_query():
    nonnegative = Invariant(
        ForAll(account, account.balance >= 0),
        id="nonnegative",
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        invariants=[nonnegative],
    )
    result = run_query(
        Reachable(
            Exists(account, account.balance == 0),
            id="an_empty_account_exists",
        ),
        spec,
        cache={},
    )
    assert result.status == "PASS"

    always = run_query(
        AlwaysHolds(
            ForAll(account, account.balance >= 0),
            id="all_nonnegative",
        ),
        spec,
        cache={},
    )
    assert always.status == "PASS"


def test_param_is_substituted_inside_quantifier_body():
    minimum = Param("minimum", 0, 1)
    audit = Action(
        id="audit",
        params=[minimum],
        pre=[ForAll(account, account.balance >= minimum)],
    )
    bound = audit.bind(minimum=1)
    scenario = Scenario(
        id="audit_minimum",
        name="Audit minimum",
        action=bound,
        given=[alice(balance=1), bob(balance=2), eve(balance=3)],
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


def test_param_is_substituted_inside_aggregate_body():
    minimum = Param("minimum", 0, 1)
    audit = Action(
        id="audit_count",
        params=[minimum],
        pre=[Count(account, account.balance >= minimum) == 3],
    )
    bound = audit.bind(minimum=1)
    scenario = Scenario(
        id="audit_count_minimum",
        name="Audit count minimum",
        action=bound,
        given=[alice(balance=1), bob(balance=2), eve(balance=3)],
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


def test_unbound_variable_is_a_structural_error():
    action = Action(id="broken", pre=[account.balance >= 0])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("outside a quantifier or aggregate" in finding.message for finding in errors)


def test_aggregate_does_not_bind_unrelated_variables():
    other = Bound("other", accounts)
    action = Action(id="broken_sum", pre=[Sum(account, other.balance) >= 0])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any(
        "Bound 'other' outside a quantifier or aggregate" in finding.message for finding in errors
    )


def test_quantifier_scope_must_be_registered():
    other_accounts = Scope(Account, keys=["mallory"], id="other_accounts")
    other = Bound("other", other_accounts)
    action = Action(id="broken", pre=[Exists(other, other.balance > 0)])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("not registered in spec.scopes" in finding.message for finding in errors)


def test_aggregate_scope_must_be_registered():
    other_accounts = Scope(Account, keys=["mallory"], id="other_accounts")
    other = Bound("other", other_accounts)
    action = Action(id="broken_sum", pre=[Sum(other, other.balance) >= 0])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("not registered in spec.scopes" in finding.message for finding in errors)


def test_exists_does_not_hide_evaluation_error_after_a_witness():
    class Mixed(Entity):
        value: object = 0

    mixed = Scope(Mixed, keys=["valid", "broken"], id="mixed")
    item = Bound("item", mixed)
    spec = Spec(id="s", name="S", entities=[Mixed], scopes=[mixed])
    result = run_query(
        Reachable(
            Exists(item, item.value > 0),
            given=[mixed["valid"](value=1), mixed["broken"](value="bad")],
            id="type_broken_exists",
        ),
        spec,
        cache={},
    )
    assert result.status == "FAIL"
    assert "evaluation error" in result.findings[0].message


def test_count_does_not_hide_evaluation_error_after_a_match():
    class Mixed(Entity):
        value: object = 0

    mixed = Scope(Mixed, keys=["valid", "broken"], id="mixed")
    item = Bound("item", mixed)
    spec = Spec(id="s", name="S", entities=[Mixed], scopes=[mixed])
    result = run_query(
        Reachable(
            Count(item, item.value > 0) >= 1,
            given=[mixed["valid"](value=1), mixed["broken"](value="bad")],
            id="type_broken_count",
        ),
        spec,
        cache={},
    )
    assert result.status == "FAIL"
    assert "evaluation error" in result.findings[0].message
