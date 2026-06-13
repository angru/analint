"""Create/Delete effects: presence as a next-state fact in a fixed universe."""

from analint import (
    Absent,
    Action,
    AlwaysHolds,
    Assert,
    Bound,
    Count,
    Create,
    Delete,
    Entity,
    Expect,
    Field,
    ForAll,
    Not,
    Param,
    Present,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Unreachable,
)
from analint.reporter.base import Severity
from analint.validator.explorer import run_query
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import validate_structural


class Account(Entity):
    balance: int = Field(0, ge=0, le=5)


accounts = Scope(Account, keys=["alice", "bob", "eve"], id="accounts")
alice = accounts["alice"]
bob = accounts["bob"]
eve = accounts["eve"]
account = Bound("account", accounts)


def _spec(actions, scenarios=()):
    return Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=list(actions),
        scenarios=list(scenarios),
    )


# ── Scenario semantics ───────────────────────────────────────────────────────


def test_create_makes_slot_present_with_given_fields():
    open_eve = Action(id="open", effect=[Create(eve, balance=2)])
    scenario = Scenario(
        id="open_eve",
        name="Open eve",
        action=open_eve,
        given=[alice(balance=1)],  # bob, eve materialise as Absent
        then=[Assert(Present(eve)), Assert(eve.balance == 2)],
    )
    result = run_scenario(scenario, _spec([open_eve], [scenario]))
    assert result.passed


def test_create_unspecified_fields_take_defaults():
    open_eve = Action(id="open", effect=[Create(eve)])
    scenario = Scenario(
        id="open_eve_default",
        name="Open eve at default",
        action=open_eve,
        given=[alice(balance=1)],
        then=[Assert(eve.balance == 0)],
    )
    assert run_scenario(scenario, _spec([open_eve], [scenario])).passed


def test_create_on_present_slot_is_pre_execution_rejection():
    reopen = Action(id="reopen", effect=[Create(alice, balance=2)])
    scenario = Scenario(
        id="reopen_alice",
        name="Reopen alice",
        action=reopen,
        given=[alice(balance=1)],
        expected=Expect.FAIL,
    )
    result = run_scenario(scenario, _spec([reopen], [scenario]))
    assert result.passed
    assert any("cannot create already-present" in f.message for f in result.findings)


def test_create_out_of_range_field_is_model_defect():
    open_bad = Action(id="open_bad", effect=[Create(eve, balance=99)])
    scenario = Scenario(
        id="open_bad", name="Open out of range", action=open_bad, given=[alice(balance=1)]
    )
    result = run_scenario(scenario, _spec([open_bad], [scenario]))
    assert not result.passed
    assert any("field constraint violated" in f.message for f in result.findings)


def test_delete_makes_slot_absent():
    close = Action(id="close", effect=[Delete(alice)])
    scenario = Scenario(
        id="close_alice",
        name="Close alice",
        action=close,
        given=[alice(balance=1)],
        then=[Assert(Not(Present(alice)))],
    )
    assert run_scenario(scenario, _spec([close], [scenario])).passed


def test_delete_absent_slot_is_pre_execution_rejection():
    close = Action(id="close", effect=[Delete(eve)])
    scenario = Scenario(
        id="close_eve",
        name="Close eve",
        action=close,
        given=[alice(balance=1)],  # eve is absent
        expected=Expect.FAIL,
    )
    result = run_scenario(scenario, _spec([close], [scenario]))
    assert result.passed
    assert any("cannot delete absent" in f.message for f in result.findings)


# ── Reachability ───────────────────────────────────────────────────────────────


def test_explorer_create_grows_present_count():
    open_eve = Action(id="open_eve", effect=[Create(eve, balance=0)])
    result = run_query(
        Reachable(
            Count(account, account.balance >= 0) == 3,
            given=[alice(balance=0), bob(balance=0), Absent(eve)],
            id="three_present",
        ),
        _spec([open_eve]),
        cache={},
    )
    assert result.status == "PASS"


def test_absent_slot_stays_absent_without_a_create():
    touch = Action(id="touch_alice", effect=[Set(alice.balance, 1)])
    result = run_query(
        Unreachable(
            Present(eve),
            given=[alice(balance=0), Absent(eve)],
            id="eve_never_appears",
        ),
        _spec([touch]),
        cache={},
    )
    assert result.status == "PASS"


def test_explorer_delete_removes_slot():
    close_alice = Action(id="close_alice", effect=[Delete(alice)])
    result = run_query(
        Reachable(Not(Present(alice)), id="alice_can_leave"),
        _spec([close_alice]),
        cache={},
    )
    assert result.status == "PASS"


def test_present_count_never_exceeds_fixed_universe():
    open_eve = Action(id="open_eve", effect=[Create(eve, balance=0)])
    result = run_query(
        AlwaysHolds(
            Count(account, account.balance >= 0) <= 3,
            given=[alice(balance=0), bob(balance=0), Absent(eve)],
            id="bounded_universe",
        ),
        _spec([open_eve]),
        cache={},
    )
    assert result.status == "PASS"


def test_parameterized_create_opens_every_slot():
    slot = Param("slot", accounts)
    open_any = Action(id="open_any", params=[slot], effect=[Create(slot, balance=0)])
    result = run_query(
        Reachable(
            ForAll(account, Present(account)),
            given=[Absent(alice), Absent(bob), Absent(eve)],
            id="all_opened",
        ),
        _spec([open_any]),
        cache={},
    )
    assert result.status == "PASS"


# ── Structural validation ───────────────────────────────────────────────────────


def _errors(spec):
    return [f for f in validate_structural(spec) if f.severity == Severity.ERROR]


def test_two_creates_on_one_slot_rejected():
    dup = Action(id="dup", effect=[Create(eve, balance=0), Create(eve, balance=1)])
    assert any("change the presence of" in f.message for f in _errors(_spec([dup])))


def test_create_and_set_on_one_slot_conflict():
    clash = Action(id="clash", effect=[Create(eve, balance=0), Set(eve.balance, 1)])
    assert any("both created/deleted and modified" in f.message for f in _errors(_spec([clash])))


def test_create_and_delete_on_one_slot_rejected():
    flip = Action(id="flip", effect=[Create(eve, balance=0), Delete(eve)])
    assert any("change the presence of" in f.message for f in _errors(_spec([flip])))


def test_create_unknown_field_rejected():
    bad = Action(id="bad", effect=[Create(eve, nonsense=1)])
    assert any("unknown field" in f.message for f in _errors(_spec([bad])))


def test_create_target_must_be_an_instance_ref():
    bad = Action(id="bad", effect=[Create(Account, balance=0)])
    assert any("must be an InstanceRef" in f.message for f in _errors(_spec([bad])))


def test_create_on_unregistered_scope_rejected():
    other = Scope(Account, keys=["zoe"], id="other")
    bad = Action(id="bad", effect=[Create(other["zoe"], balance=0)])
    assert any("not registered in spec.scopes" in f.message for f in _errors(_spec([bad])))
