"""Bounded multiplicity: finite identified instances of one Entity type."""

from enum import StrEnum

from analint import (
    Action,
    Add,
    Entity,
    Field,
    Lifecycle,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Subtract,
    Transition,
)
from analint.reporter.base import Severity
from analint.validator.engine import build_spec
from analint.validator.explorer import run_query
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import validate_structural


class Account(Entity):
    balance: int = Field(0, ge=0, le=5)


accounts = Scope(Account, keys=["alice", "bob", "eve"], id="accounts")
alice = accounts["alice"]
bob = accounts["bob"]
eve = accounts["eve"]


def _transfer() -> Action:
    src = Param("src", accounts)
    dst = Param("dst", accounts)
    amount = Param("amount", 1, 2)
    return Action(
        id="transfer",
        params=[src, dst, amount],
        where=[src != dst],
        pre=[src.balance >= amount, dst.balance <= 5 - amount],
        effect=[Subtract(src.balance, amount), Add(dst.balance, amount)],
    )


def test_scope_creates_stable_instance_refs_and_identified_snapshots():
    assert accounts["alice"] is alice
    assert list(accounts) == [alice, bob, eve]
    assert repr(alice(balance=3)) == "Account['alice'](balance=3)"


def test_param_expands_over_instances_not_entity_classes():
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[_transfer()],
    )
    assert len(spec.actions) == 12  # 3 src * 2 different dst * 2 amounts
    assert any("src=Account['alice']" in action.id for action in spec.actions)


def test_scenario_updates_two_instances_simultaneously():
    transfer = _transfer()
    bound = transfer.bind(src=alice, dst=bob, amount=2)
    scenario = Scenario(
        id="alice_pays_bob",
        name="Alice pays Bob",
        action=bound,
        given=[alice(balance=3), bob(balance=1), eve(balance=0)],
        then=[alice.balance == 1, bob.balance == 3],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[transfer],
        scenarios=[scenario],
    )
    result = run_scenario(scenario, spec)
    assert result.passed, [f.message for f in result.findings]


def test_effect_rhs_reads_multiplicity_pre_state():
    swap = Action(
        id="swap",
        effect=[
            Set(alice.balance, bob.balance),
            Set(bob.balance, alice.balance),
        ],
    )
    scenario = Scenario(
        id="swap_balances",
        name="Swap balances",
        action=swap,
        given=[alice(balance=4), bob(balance=1)],
        then=[alice.balance == 1, bob.balance == 4],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[swap],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed


def test_explorer_builds_all_scope_defaults_and_finds_instance_trace():
    transfer = _transfer()
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[transfer],
    )
    query = Reachable(
        bob.balance == 2,
        given=[alice(balance=2)],
        id="bob_can_receive_two",
    )
    result = run_query(query, spec, cache={})
    assert result.status == "PASS"
    assert result.trace is not None
    assert any("src=Account['alice']" in step for step in result.trace)


def test_class_field_is_rejected_when_entity_has_multiple_instances():
    ambiguous = Action(id="ambiguous", pre=[Account.balance > 0])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[ambiguous],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("Account.balance" in f.message and "ambiguous" in f.message for f in errors)


def test_instance_ref_from_unregistered_scope_is_rejected():
    other_accounts = Scope(Account, keys=["mallory"], id="other_accounts")
    mallory = other_accounts["mallory"]
    action = Action(id="touch_mallory", effect=[Set(mallory.balance, 1)])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[action],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("not registered in spec.scopes" in f.message for f in errors)


def test_plain_snapshot_is_rejected_for_scoped_entity():
    transfer = _transfer()
    bound = transfer.bind(src=alice, dst=bob, amount=1)
    scenario = Scenario(
        id="unidentified_account",
        name="Unidentified account",
        action=bound,
        given=[Account(balance=2), bob(balance=0)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[transfer],
        scenarios=[scenario],
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("registered InstanceRef" in f.message for f in errors)

    result = run_query(
        Reachable(bob.balance == 1, given=[Account(balance=2)], id="bad_initial"),
        spec,
        cache={},
    )
    assert result.status == "FAIL"
    assert "registered InstanceRef" in result.findings[0].message


def test_field_bounds_apply_to_each_instance():
    overpay = Action(id="overpay", effect=[Add(bob.balance, 6)])
    scenario = Scenario(
        id="overpay",
        name="Overpay",
        action=overpay,
        given=[bob(balance=0)],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[overpay],
        scenarios=[scenario],
    )
    result = run_scenario(scenario, spec)
    assert not result.passed
    assert any("field constraint violated" in f.message for f in result.findings)


def test_terminal_lifecycle_blocks_only_target_instance():
    class Status(StrEnum):
        OPEN = "open"
        DONE = "done"

    class Ticket(Entity):
        status: Status = Lifecycle(
            initial=Status.OPEN,
            transitions=[Transition(Status.OPEN, [Status.DONE])],
            terminal=[Status.DONE],
        )

    tickets = Scope(Ticket, keys=["a", "b"], id="tickets")
    a = tickets["a"]
    b = tickets["b"]
    finish_b = Action(id="finish_b", effect=[Set(b.status, Status.DONE)])
    scenario = Scenario(
        id="finish_open_ticket",
        name="Finish B",
        action=finish_b,
        given=[a(status=Status.DONE), b(status=Status.OPEN)],
        then=[b.status == Status.DONE],
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Ticket],
        scopes=[tickets],
        actions=[finish_b],
        scenarios=[scenario],
    )
    assert run_scenario(scenario, spec).passed


def test_loader_discovers_scope_and_derives_its_id(tmp_path):
    spec_file = tmp_path / "spec.py"
    spec_file.write_text(
        """
from analint import Action, Entity, Field, Scope, Set, Spec

class Account(Entity):
    balance: int = Field(0, ge=0, le=2)

accounts = Scope(Account, keys=["alice", "bob"])
seed_alice = Action(effect=[Set(accounts["alice"].balance, 1)])
spec = Spec(id="scoped", name="Scoped")
"""
    )
    spec, _, errors = build_spec(spec_file)
    assert not errors
    assert spec is not None
    assert spec.scopes[0].id == "accounts"
    assert [repr(ref) for ref in spec.scopes[0]] == [
        "Account['alice']",
        "Account['bob']",
    ]
