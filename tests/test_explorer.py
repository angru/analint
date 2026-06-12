from enum import Enum
from pathlib import Path

from analint import (
    Action,
    Add,
    AlwaysHolds,
    DeadActions,
    Entity,
    Field,
    Invariant,
    Lifecycle,
    NoDeadEnd,
    Reachable,
    Set,
    Spec,
    Subtract,
    Transition,
    Unreachable,
)
from analint.validator.engine import validate
from analint.validator.explorer import build_initial, run_query

TROLLBRIDGE = Path(__file__).parent.parent / "examples" / "trollbridge"
CLOAK = Path(__file__).parent.parent / "examples" / "cloak"


def _run(query, spec):
    return run_query(query, spec, cache={})


# ── Reachable / Unreachable ────────────────────────────────────────────────────


def _switch_spec():
    class Lamp(Entity):
        on: bool = False

    toggle_on = Action(
        id="turn_on",
        pre=[Lamp.on == False],  # noqa: E712
        effect=[Set(Lamp.on, True)],
    )
    return Lamp, Spec(id="s", name="S", entities=[Lamp], actions=[toggle_on])


def test_reachable_pass_with_witness_trace():
    Lamp, spec = _switch_spec()
    result = _run(Reachable(Lamp.on == True, id="q"), spec)  # noqa: E712
    assert result.status == "PASS"
    assert result.trace == ["turn_on"]


def test_reachable_fail_when_no_path():
    class Door(Entity):
        open: bool = False

    spec = Spec(id="s", name="S", entities=[Door], actions=[])
    result = _run(Reachable(Door.open == True, id="q"), spec)  # noqa: E712
    assert result.status == "FAIL"
    assert "not reachable" in result.findings[0].message


def test_unreachable_fail_with_counterexample():
    Lamp, spec = _switch_spec()
    result = _run(Unreachable(Lamp.on == True, id="q"), spec)  # noqa: E712
    assert result.status == "FAIL"
    assert result.trace == ["turn_on"]


def test_unreachable_pass():
    Lamp, spec = _switch_spec()
    result = _run(Unreachable(Lamp.on == None, id="q"), spec)  # noqa: E711
    assert result.status == "PASS"


# ── AlwaysHolds ────────────────────────────────────────────────────────────────


def test_always_holds_fail_with_offending_values():
    class Tank(Entity):
        fuel: int = Field(5, ge=-10, le=10)

    burn = Action(id="burn", pre=[Tank.fuel >= 0], effect=[Subtract(Tank.fuel, 3)])
    spec = Spec(id="s", name="S", entities=[Tank], actions=[burn])
    result = _run(AlwaysHolds(Tank.fuel >= 0, id="q"), spec)
    assert result.status == "FAIL"
    assert "Tank.fuel=-1" in result.findings[0].message
    assert result.trace == ["burn", "burn"]  # 5 → 2 → -1


# ── NoDeadEnd ──────────────────────────────────────────────────────────────────


def test_no_dead_end_detects_softlock():
    class Purse(Entity):
        gold: int = 6
        has_sword: bool = False
        done: bool = False

    buy_sword = Action(
        id="buy_sword",
        pre=[Purse.gold >= 5],
        effect=[Subtract(Purse.gold, 5), Set(Purse.has_sword, True)],
    )
    waste = Action(id="waste", pre=[Purse.gold >= 3], effect=[Subtract(Purse.gold, 3)])
    win = Action(
        id="win",
        pre=[Purse.has_sword == True],  # noqa: E712
        effect=[Set(Purse.done, True)],
    )
    spec = Spec(id="s", name="S", entities=[Purse], actions=[buy_sword, waste, win])
    result = _run(NoDeadEnd(Purse.done == True, id="q"), spec)  # noqa: E712
    assert result.status == "FAIL"
    assert result.trace == ["waste"]  # 3 gold left → the sword is gone forever


def test_no_dead_end_pass():
    Lamp, spec = _switch_spec()
    result = _run(NoDeadEnd(Lamp.on == True, id="q"), spec)  # noqa: E712
    assert result.status == "PASS"


# ── DeadActions ────────────────────────────────────────────────────────────────


def test_dead_actions_reported():
    class Box(Entity):
        sealed: bool = True

    open_box = Action(
        id="open_box",
        pre=[Box.sealed == False],  # noqa: E712
        effect=[Set(Box.sealed, True)],
    )
    spec = Spec(id="s", name="S", entities=[Box], actions=[open_box])
    result = _run(DeadActions(id="q"), spec)
    assert result.status == "FAIL"
    assert "open_box" in result.findings[0].message


# ── Field constraints ──────────────────────────────────────────────────────────


def test_field_constraint_violation_pruned_and_reported():
    class Meter(Entity):
        value: int = Field(0, ge=0, le=10)

    pump = Action(id="pump", effect=[Add(Meter.value, 7)])
    spec = Spec(id="s", name="S", entities=[Meter], actions=[pump])
    result = _run(Reachable(Meter.value >= 14, id="q"), spec)
    assert result.status == "FAIL"  # 14 pruned at the bound


def test_field_constraint_saturate_clamps():
    class Meter(Entity):
        value: int = Field(0, ge=0, le=10, saturate=True)

    pump = Action(id="pump", effect=[Add(Meter.value, 7)])
    spec = Spec(id="s", name="S", entities=[Meter], actions=[pump])
    result = _run(Reachable(Meter.value == 10, id="q"), spec)
    assert result.status == "PASS"  # 0 → 7 → clamp(14)=10


def test_unbounded_counter_is_inconclusive():
    class Meter(Entity):
        value: int = 0

    pump = Action(id="pump", effect=[Add(Meter.value, 1)])
    spec = Spec(id="s", name="S", entities=[Meter], actions=[pump])
    result = _run(Reachable(Meter.value < 0, id="q", max_states=50), spec)
    assert result.status == "INCONCLUSIVE"


# ── Exploration-time model checks ─────────────────────────────────────────────


def test_undeclared_lifecycle_transition_found():
    class S(Enum):
        A = "a"
        B = "b"
        C = "c"

    class Thing(Entity):
        state: S = Lifecycle(
            initial=S.A,
            transitions=[
                Transition(S.A, [S.B]),
                Transition(S.B, [S.C]),
            ],
        )

    jump = Action(id="jump", pre=[Thing.state == S.A], effect=[Set(Thing.state, S.C)])
    spec = Spec(id="s", name="S", entities=[Thing], actions=[jump])

    cache: dict = {}
    result = run_query(Reachable(Thing.state == S.C, id="q"), spec, cache)
    assert result.status == "FAIL"  # the A→C shortcut is pruned as undeclared
    exp = next(iter(cache.values()))
    assert any("not declared in" in f.message for f in exp.findings)


def test_invariant_violation_found_during_exploration():
    class Acc(Entity):
        balance: int = Field(5, ge=-100, le=100)

    spend = Action(id="spend", effect=[Subtract(Acc.balance, 4)])
    inv = Invariant(Acc.balance >= 0, label="No overdraft", id="inv")
    spec = Spec(id="s", name="S", entities=[Acc], actions=[spend], invariants=[inv])

    cache: dict = {}
    run_query(DeadActions(id="q"), spec, cache)
    exp = next(iter(cache.values()))
    assert any("No overdraft" in f.message and "spend" in f.message for f in exp.findings)


def test_initial_state_requires_given_for_entities_without_defaults():
    class Order(Entity):
        total: float  # required, no default

    pay = Action(id="pay", pre=[Order.total > 0])
    spec = Spec(id="s", name="S", entities=[Order], actions=[pay])
    initial, error = build_initial(spec, given=[])
    assert initial is None
    assert "Order" in error

    initial, error = build_initial(spec, given=[Order(total=5.0)])
    assert error is None


# ── Integration: the examples ──────────────────────────────────────────────────


def test_trollbridge_engine_finds_planted_bugs():
    result = validate(TROLLBRIDGE)
    assert result.failed_count == 0  # every scenario is green…
    by_id = {qr.query_id: qr for qr in result.query_results}
    assert by_id["bridge_is_reachable"].status == "PASS"
    assert by_id["bridge_is_reachable"].trace == ["buy_sword", "fight_troll", "cross_bridge"]
    assert by_id["no_softlock"].status == "FAIL"
    assert by_id["no_softlock"].trace == ["buy_potion"]
    assert by_id["hp_never_negative"].status == "FAIL"
    assert by_id["no_gold_from_thin_air"].status == "PASS"
    assert result.has_errors  # …but the model is broken


def test_cloak_all_queries_pass():
    result = validate(CLOAK)
    assert not result.has_errors
    assert {qr.status for qr in result.query_results} == {"PASS"}
    win = next(qr for qr in result.query_results if qr.query_id == "win_is_reachable")
    assert win.trace == ["go_west", "hang_cloak", "go_east", "go_south", "read_message_win"]


def test_fulfillment_saga_all_green():
    result = validate(Path(__file__).parent.parent / "examples" / "fulfillment")
    assert not result.has_errors, [f.message for f in result.exploration_findings]
    by_id = {qr.query_id: qr for qr in result.query_results}
    assert by_id["saga_always_settles"].status == "PASS"
    assert by_id["happy_path_exists"].trace == [
        "supplier_restock",
        "reserve_stock",
        "authorize_payment",
        "confirm_order",
        "capture_payment",
        "dispatch",
        "confirm_delivery",
    ]
    assert by_id["no_money_for_nothing"].status == "PASS"
    assert by_id["every_step_used"].status == "PASS"


def test_coin_translation_reproduces_quint_lesson_violation():
    result = validate(Path(__file__).parent.parent / "examples" / "coin")
    by_id = {qr.query_id: qr for qr in result.query_results}
    overflow = by_id["supply_never_overflows"]
    assert overflow.status == "FAIL"  # the Quint lesson's teaching moment
    # minimal counterexample: two mints of 3 already break the supply bound
    assert overflow.trace is not None and len(overflow.trace) == 2
    assert all(step.startswith("mint(") for step in overflow.trace)
    assert by_id["everyone_can_get_paid"].status == "PASS"
    assert by_id["every_method_callable"].status == "PASS"
    assert result.failed_count == 0  # all translated Quint tests pass
