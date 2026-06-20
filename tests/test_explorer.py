from enum import Enum
from pathlib import Path

import pytest
from pydantic import ValidationError

from analint import (
    Action,
    Add,
    AlwaysHolds,
    Bound,
    Count,
    DeadActions,
    Entity,
    Event,
    Field,
    Initial,
    Invariant,
    Lifecycle,
    NoDeadEnd,
    Reachable,
    Scope,
    Set,
    Spec,
    Subtract,
    Transition,
    Unreachable,
)
from analint.reporter.base import Severity
from analint.validator.engine import validate
from analint.validator.explorer import (
    build_canonical_initials,
    build_initial,
    run_query,
    verify_invariants,
)
from analint.validator.structural import validate_structural

TROLLBRIDGE = Path(__file__).parent.parent / "examples" / "trollbridge"
CLOAK = Path(__file__).parent.parent / "examples" / "cloak"


def _run(query, spec):
    return run_query(query, spec, cache={})


def _verify(spec, max_states=10_000):
    initials, error = build_canonical_initials(spec)
    return verify_invariants(spec, initials, build_error=error, max_states=max_states)


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


def test_explorer_rejects_action_whose_post_is_false():
    # The effect sets PAID, but the declared post lies (CANCELLED). The explorer
    # must report it and prune the edge, not accept the transition (research/18 §2.1).
    class S(Enum):
        PENDING = "pending"
        PAID = "paid"
        CANCELLED = "cancelled"

    class Order(Entity):
        status: S = Field(S.PENDING)

    pay = Action(
        id="pay",
        pre=[Order.status == S.PENDING],
        effect=[Set(Order.status, S.PAID)],
        post=[Order.status == S.CANCELLED],  # contradicts the effect
    )
    spec = Spec(id="s", name="S", entities=[Order], actions=[pay])

    cache: dict = {}
    result = run_query(Reachable(Order.status == S.PAID, id="q"), spec, cache)
    assert result.status == "FAIL"  # PAID edge is pruned by the post violation
    exp = next(iter(cache.values()))
    assert any("postcondition" in f.message and "pay" in f.message for f in exp.findings)


def test_explorer_accepts_action_whose_post_holds():
    class S(Enum):
        PENDING = "pending"
        PAID = "paid"

    class Order(Entity):
        status: S = Field(S.PENDING)

    pay = Action(
        id="pay",
        pre=[Order.status == S.PENDING],
        effect=[Set(Order.status, S.PAID)],
        post=[Order.status == S.PAID],  # honest
    )
    spec = Spec(id="s", name="S", entities=[Order], actions=[pay])
    result = run_query(Reachable(Order.status == S.PAID, id="q"), spec, cache={})
    assert result.status == "PASS"


def test_effectless_action_still_checks_post():
    # An action with no effect but a false post must be reported, not a silent
    # self-loop (review 584d819 P1).
    class Box(Entity):
        n: int = Field(0, ge=0, le=3)

    check = Action(id="check", post=[Box.n == 1])  # false at n=0, no effect
    spec = Spec(id="s", name="S", entities=[Box], actions=[check])

    cache: dict = {}
    run_query(Reachable(Box.n == 0, id="q"), spec, cache)
    exp = next(iter(cache.values()))
    assert any("postcondition" in f.message and "check" in f.message for f in exp.findings)


def test_effectless_action_with_true_post_is_a_clean_self_loop():
    class Box(Entity):
        n: int = Field(0, ge=0, le=3)

    noop = Action(id="noop", post=[Box.n == 0])  # holds at n=0
    spec = Spec(id="s", name="S", entities=[Box], actions=[noop])
    result = run_query(Reachable(Box.n == 0, id="q"), spec, cache={})
    assert result.status == "PASS"


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
    assert by_id["settlement_always_reachable"].status == "PASS"
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
    assert overflow.states_explored == 216  # Scope migration preserves the graph
    # minimal counterexample: two mints of 3 already break the supply bound
    assert overflow.trace is not None and len(overflow.trace) == 2
    assert all(step.startswith("mint(") for step in overflow.trace)
    assert by_id["everyone_can_get_paid"].status == "PASS"
    assert by_id["balances_stay_in_range"].status == "PASS"
    assert by_id["every_method_callable"].status == "PASS"
    assert result.failed_count == 0  # all translated Quint tests pass


# ── Initial-state sets (research/16) ──────────────────────────────────────────


def test_given_any_quantifies_over_all_roots():
    class Door(Entity):
        locked: bool = True
        open: bool = False

    push = Action(
        id="push",
        pre=[Door.locked == False, Door.open == False],  # noqa: E712
        effect=[Set(Door.open, True)],
    )
    spec = Spec(id="s", name="S", entities=[Door], actions=[push])

    # from the default (locked) root alone the door never opens…
    one = run_query(Reachable(Door.open == True, id="q1"), spec, cache={})  # noqa: E712
    assert one.status == "FAIL"

    # …but over the set of admissible initials it does — and the verdict
    # names the originating configuration
    many = run_query(
        Reachable(
            Door.open == True,  # noqa: E712
            id="q2",
            given_any=[[Door(locked=True)], [Door(locked=False)]],
        ),
        spec,
        cache={},
    )
    assert many.status == "PASS"
    assert any("init #2" in f.message for f in many.findings)


def test_always_holds_must_survive_every_root():
    class Tank(Entity):
        fuel: int = 5

    spec = Spec(id="s", name="S", entities=[Tank], actions=[])
    result = run_query(
        AlwaysHolds(
            Tank.fuel >= 3,
            id="q",
            given_any=[[Tank(fuel=5)], [Tank(fuel=1)]],  # breaks in root #2
        ),
        spec,
        cache={},
    )
    assert result.status == "FAIL"
    assert any("init #2" in f.message for f in result.findings)


def test_given_and_given_any_together_is_an_error():
    class Tank(Entity):
        fuel: int = 5

    spec = Spec(id="s", name="S", entities=[Tank], actions=[])
    result = run_query(
        Reachable(Tank.fuel == 5, id="q", given=[Tank()], given_any=[[Tank()]]),
        spec,
        cache={},
    )
    assert result.status == "FAIL"
    assert any("not both" in f.message for f in result.findings)


def test_duplicate_roots_merge():
    class Tank(Entity):
        fuel: int = 5

    spec = Spec(id="s", name="S", entities=[Tank], actions=[])
    result = run_query(
        Reachable(Tank.fuel == 5, id="q", given_any=[[Tank(fuel=5)], [Tank(fuel=5)]]),
        spec,
        cache={},
    )
    assert result.status == "PASS"
    assert result.states_explored == 1


def test_declarative_initial_relation_varies_finite_fields():
    class Door(Entity):
        locked: bool = True
        open: bool = False

    push = Action(
        id="push",
        pre=[Door.locked == False, Door.open == False],  # noqa: E712
        effect=[Set(Door.open, True)],
    )
    initials = Initial(vary=[Door.locked])
    spec = Spec(id="s", name="S", entities=[Door], actions=[push])

    result = run_query(
        Reachable(Door.open == True, id="q", initial=initials),  # noqa: E712
        spec,
        cache={},
    )
    assert result.status == "PASS"
    assert result.states_explored == 3
    assert any("init #1" in finding.message for finding in result.findings)


def test_initial_relation_filters_scoped_domains_with_aggregates():
    class Role(Enum):
        MAFIA = "mafia"
        CITIZEN = "citizen"

    class Player(Entity):
        role: Role = Role.CITIZEN

    players = Scope(Player, keys=["a", "b", "c"], id="players")
    player = Bound("player", players)
    exactly_one_mafia = Count(player, player.role == Role.MAFIA) == 1
    initials = Initial(vary=[player.role], where=[exactly_one_mafia])
    spec = Spec(id="s", name="S", entities=[Player], scopes=[players])

    result = run_query(
        AlwaysHolds(exactly_one_mafia, id="q", initial=initials),
        spec,
        cache={},
    )
    assert result.status == "PASS"
    assert result.states_explored == 3


def test_initial_relation_uses_explicit_field_values():
    class Mode(Entity):
        name: str = Field("draft", values=["draft", "published"])

    spec = Spec(id="s", name="S", entities=[Mode])
    result = run_query(
        Reachable(
            Mode.name == "published",
            id="q",
            initial=Initial(vary=[Mode.name]),
        ),
        spec,
        cache={},
    )
    assert result.status == "PASS"
    assert result.states_explored == 2


def test_initial_relation_infers_domain_from_required_given_value():
    class Switch(Entity):
        enabled: bool

    spec = Spec(id="s", name="S", entities=[Switch])
    result = run_query(
        Reachable(
            Switch.enabled == False,  # noqa: E712
            id="q",
            initial=Initial(
                vary=[Switch.enabled],
                given=[Switch(enabled=True)],
            ),
        ),
        spec,
        cache={},
    )
    assert result.status == "PASS"
    assert result.states_explored == 2


def test_initial_relation_rejects_unbounded_and_oversized_domains():
    class FreeText(Entity):
        value: str = "anything"

    spec = Spec(id="s", name="S", entities=[FreeText])
    unbounded = run_query(
        Reachable(
            FreeText.value == "x",
            id="unbounded",
            initial=Initial(vary=[FreeText.value]),
        ),
        spec,
        cache={},
    )
    assert unbounded.status == "FAIL"
    assert "cannot infer a finite domain" in unbounded.findings[0].message

    class Number(Entity):
        value: int = Field(0, ge=0, le=10)

    limited = run_query(
        Reachable(
            Number.value == 5,
            id="limited",
            initial=Initial(vary=[Number.value], max_candidates=5),
        ),
        Spec(id="numbers", name="Numbers", entities=[Number]),
        cache={},
    )
    assert limited.status == "FAIL"
    assert "11 candidates" in limited.findings[0].message


def test_initial_relation_rejects_empty_and_broken_relations():
    class Value(Entity):
        item: object = Field(1, values=[1, "broken"])

    spec = Spec(id="s", name="S", entities=[Value])
    empty = run_query(
        Reachable(
            Value.item == 1,
            id="empty",
            initial=Initial(vary=[Value.item], where=[Value.item != Value.item]),
        ),
        spec,
        cache={},
    )
    assert empty.status == "FAIL"
    assert "matches no states" in empty.findings[0].message

    broken = run_query(
        Reachable(
            Value.item == 1,
            id="broken",
            initial=Initial(vary=[Value.item], where=[Value.item > 0]),
        ),
        spec,
        cache={},
    )
    assert broken.status == "FAIL"
    assert "where evaluation error" in broken.findings[0].message


def test_initial_relation_is_structurally_validated():
    class Player(Entity):
        alive: bool = True

    registered = Scope(Player, keys=["a"], id="registered")
    other = Scope(Player, keys=["b"], id="other")
    outsider = Bound("outsider", other)
    query = AlwaysHolds(
        Player.alive == True,  # noqa: E712
        id="q",
        initial=Initial(vary=[outsider.alive]),
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Player],
        scopes=[registered],
        queries=[query],
    )
    findings = validate_structural(spec)
    assert any("not registered in spec.scopes" in finding.message for finding in findings)


def test_mafia_theorem_quantifies_over_role_assignments():
    result = validate(Path(__file__).parent.parent / "examples" / "mafia")
    assert not result.has_errors
    by_id = {qr.query_id: qr for qr in result.query_results}
    assert by_id["citizens_cannot_win"].status == "PASS"
    assert by_id["mafia_can_win"].status == "PASS"
    assert by_id["mafia_can_win"].states_explored == 36  # 12 states × 3 assignments


def test_query_without_a_source_starts_from_spec_initial():
    """A query that names no given/given_any/initial uses the spec's canonical
    initial, so checks share one state space unless they opt out."""

    class Box(Entity):
        n: int = Field(0, ge=0, le=3)

    spec = Spec(id="s", name="S", entities=[Box], initial=Initial(vary=[Box.n]))

    # spec.initial varies n over 0..3, so n == 3 is one of the roots
    assert _run(Reachable(Box.n == 3), spec).status == "PASS"
    # opting out with an explicit given falls back to the defaults-only root
    assert _run(Reachable(Box.n == 3, given=[Box(n=0)]), spec).status == "FAIL"


# ── canonical invariant verification ────────────────────────────────────────────


class _Counter(Entity):
    n: int = Field(0, ge=0, le=3)


def _counter_spec(invariant):
    bump = Action(id="bump", pre=[_Counter.n < 3], effect=[Add(_Counter.n, 1)])
    return Spec(id="s", name="S", entities=[_Counter], actions=[bump], invariants=[invariant])


def test_invariant_pass_over_canonical_model():
    spec = _counter_spec(Invariant(_Counter.n >= 0, id="non_negative"))
    (res,), _ = _verify(spec)
    assert res.status == "PASS"
    assert res.states_explored == 4  # n = 0..3


def test_invariant_fail_reports_a_trace_to_the_violating_state():
    spec = _counter_spec(Invariant(_Counter.n <= 1, id="small"))
    (res,), _ = _verify(spec)
    assert res.status == "FAIL"
    assert res.trace == ["bump", "bump"]  # reaches n == 2, the first violation


def test_invariant_inconclusive_when_exploration_is_capped():
    spec = _counter_spec(Invariant(_Counter.n >= 0, id="non_negative"))
    (res,), _ = _verify(spec, max_states=2)
    assert res.status == "INCONCLUSIVE"


def test_invariant_not_checked_when_canonical_state_cannot_be_built():
    class Need(Entity):
        id: str  # no default, so a defaults-only root cannot be built

    spec = Spec(
        id="s", name="S", entities=[Need], invariants=[Invariant(Need.id != "", id="has_id")]
    )
    (res,), _ = _verify(spec)
    assert res.status == "NOT_CHECKED"
    assert any("could not build" in f.message for f in res.findings)


def test_canonical_verification_surfaces_transition_defects():
    """A broken action during canonical verification must reach the result, not
    be hidden behind a green invariant (review 67be4f8, P1#1)."""

    class Box(Entity):
        value: int = 0

    broken = Action(id="broken", effect=[Set(Box.value, Box.value + "bad")])
    spec = Spec(
        id="s",
        name="S",
        entities=[Box],
        actions=[broken],
        invariants=[Invariant(Box.value >= 0, id="non_negative")],
    )
    _results, exp = _verify(spec)
    assert exp is not None
    assert any(f.severity == Severity.ERROR for f in exp.findings)  # not discarded


def test_spec_initial_is_structurally_validated():
    """Spec.initial is part of the model, so a foreign vary field is an error
    even with no queries (review 67be4f8, P1#2)."""

    class Registered(Entity):
        enabled: bool = False

    class Foreign(Entity):
        enabled: bool = False

    spec = Spec(id="s", name="S", entities=[Registered], initial=Initial(vary=[Foreign.enabled]))
    findings = validate_structural(spec)
    assert any("Foreign" in f.message and "not in spec.entities" in f.message for f in findings)


def test_invariant_inconclusive_when_an_action_is_excluded():
    """An invariant with no counterexample cannot claim PASS while part of the
    transition relation is unexplorable (review 67be4f8, P1#3)."""

    class Signal(Event):
        ok: bool

    class Box(Entity):
        value: int = 0

    event_step = Action(id="ev", on=[Signal], pre=[Signal.ok == True], effect=[Set(Box.value, 1)])  # noqa: E712
    spec = Spec(
        id="s",
        name="S",
        entities=[Box],
        events=[Signal],
        actions=[event_step],
        invariants=[Invariant(Box.value == 0, id="stays_zero")],
    )
    (res,), _ = _verify(spec)
    assert res.status == "INCONCLUSIVE"
    assert any("excluded" in f.message for f in res.findings)


def test_spec_initial_given_must_be_registered():
    """given= snapshots seed canonical roots, so a foreign entity is an error
    (review c893ca0, P2)."""

    class Registered(Entity):
        enabled: bool = False

    class Foreign(Entity):
        enabled: bool = False

    spec = Spec(
        id="s",
        name="S",
        entities=[Registered],
        initial=Initial(vary=[Registered.enabled], given=[Foreign()]),
    )
    findings = validate_structural(spec)
    assert any("Foreign" in f.message and "not in spec.entities" in f.message for f in findings)


def test_spec_max_states_must_be_positive():
    """A non-positive budget is an invalid configuration, not an exhausted one
    (review c893ca0, P2)."""

    class Box(Entity):
        n: int = 0

    for bad in (0, -1):
        with pytest.raises(ValidationError):
            Spec(id="s", name="S", entities=[Box], max_states=bad)


def test_canonical_invariant_over_a_deleted_slot_stays_pass():
    """After Delete the slot's key stays in context as Absent; the invariant over
    it must be inapplicable, not a false FAIL (review 8cca900, P0)."""
    from analint import Delete

    class Account(Entity):
        balance: int = Field(0, ge=-5, le=5)

    accounts = Scope(Account, keys=["a"], id="accounts")
    ref = accounts["a"]
    close = Action(id="close", effect=[Delete(ref)])
    spec = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[close],
        invariants=[Invariant(ref.balance >= 0, id="non_negative")],
    )
    (res,), _ = _verify(spec)
    assert res.status == "PASS"
