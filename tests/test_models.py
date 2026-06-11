from enum import Enum

from analint import (
    Action,
    Actor,
    Add,
    And,
    Assert,
    Emitted,
    Entity,
    Event,
    Expect,
    Field,
    Flow,
    Implies,
    Invariant,
    Lifecycle,
    Not,
    Scenario,
    Set,
    Spec,
    Subtract,
    Transition,
)
from analint.models.entity import FieldDescriptor
from analint.models.predicate import _And, _Eq, _Gt, _Gte, _Implies, _Not
from analint.validator.rule_checker import evaluate

# ── Entity DSL ─────────────────────────────────────────────────────────────────


def test_entity_class_field_access_returns_descriptor():
    class Order(Entity):
        total: float

    assert isinstance(Order.total, FieldDescriptor)
    assert Order.total.field_name == "total"
    assert Order.total.entity_cls is Order


def test_entity_instance_field_access_returns_value():
    class Order(Entity):
        total: float

    o = Order(total=42.0)
    assert o.total == 42.0


def test_entity_default_field():
    class Item(Entity):
        active: bool = True
        price: float

    i = Item(price=5.0)
    assert i.active is True
    assert i.price == 5.0


def test_field_constraints_validate_instances():
    class Item(Entity):
        stock: int = Field(0, ge=0, le=10)

    assert Item(stock=10).stock == 10
    try:
        Item(stock=-1)
        assert False, "should have raised"
    except ValueError as exc:
        assert "must be >= 0" in str(exc)


def test_field_constraint_checks_post_state():
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        stock: int = Field(0, ge=0)

    consume = Action(id="consume", effect=[Subtract(Item.stock, 1)])
    scenario = Scenario(id="sc", action=consume, given=[Item()])
    spec = Spec(id="s", name="S", entities=[Item], actions=[consume], scenarios=[scenario])

    result = run_scenario(scenario, spec)
    assert not result.passed
    assert any("field constraint violated" in finding.message for finding in result.findings)


def test_saturating_field_clamps_before_postconditions():
    from analint.validator.scenario_runner import run_scenario

    class Meter(Entity):
        value: int = Field(0, ge=0, le=10, saturate=True)

    pump = Action(
        id="pump",
        effect=[Add(Meter.value, 20)],
        post=[Meter.value == 10],
    )
    scenario = Scenario(id="sc", action=pump, given=[Meter()])
    spec = Spec(id="s", name="S", entities=[Meter], actions=[pump], scenarios=[scenario])

    assert run_scenario(scenario, spec).passed


def test_entity_missing_required_field_raises():
    class Item(Entity):
        price: float

    try:
        Item()
        assert False, "should have raised"
    except TypeError as e:
        assert "price" in str(e)


def test_entity_unknown_field_raises():
    class Item(Entity):
        price: float

    try:
        Item(price=1.0, weight=2.0)
        assert False, "should have raised"
    except TypeError as e:
        assert "weight" in str(e)


def test_entity_repr():
    class Widget(Entity):
        name: str
        price: float

    w = Widget(name="bolt", price=1.5)
    assert "Widget" in repr(w)
    assert "bolt" in repr(w)


# ── Operator overloading → predicates ─────────────────────────────────────────


def test_ge_returns_gte_predicate():
    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    pred = Wallet.balance >= Order.total
    assert isinstance(pred, _Gte)


def test_gt_returns_gt_predicate():
    class Product(Entity):
        stock: int

    pred = Product.stock > 0
    assert isinstance(pred, _Gt)


def test_eq_returns_eq_predicate():
    class Status(Enum):
        PENDING = "pending"

    class Order(Entity):
        status: Status

    pred = Order.status == Status.PENDING
    assert isinstance(pred, _Eq)


def test_logical_and():
    class A(Entity):
        x: int

    pred = And(A.x > 0, A.x < 100)
    assert isinstance(pred, _And)
    assert len(pred.exprs) == 2


def test_logical_not():
    class A(Entity):
        x: int

    pred = Not(A.x > 0)
    assert isinstance(pred, _Not)


def test_implies_returns_implies_predicate():
    class A(Entity):
        x: int
        y: int

    pred = Implies(A.x > 0, A.y > 0)
    assert isinstance(pred, _Implies)


# ── Predicate evaluation ───────────────────────────────────────────────────────


def _ctx(*instances):
    return {type(inst): inst for inst in instances}


def test_evaluate_gte_pass():
    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    pred = Wallet.balance >= Order.total
    ctx = _ctx(Wallet(balance=100.0), Order(total=50.0))
    assert evaluate(pred, ctx) is True


def test_evaluate_gte_fail():
    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    pred = Wallet.balance >= Order.total
    ctx = _ctx(Wallet(balance=10.0), Order(total=50.0))
    assert evaluate(pred, ctx) is False


def test_evaluate_gt_literal():
    class Product(Entity):
        stock: int

    pred = Product.stock > 0
    assert evaluate(pred, _ctx(Product(stock=5))) is True
    assert evaluate(pred, _ctx(Product(stock=0))) is False


def test_evaluate_eq_enum():
    class Status(Enum):
        PENDING = "pending"
        PAID = "paid"

    class Order(Entity):
        status: Status

    pred = Order.status == Status.PENDING
    assert evaluate(pred, _ctx(Order(status=Status.PENDING))) is True
    assert evaluate(pred, _ctx(Order(status=Status.PAID))) is False


def test_evaluate_and():
    class Item(Entity):
        price: float
        stock: int

    pred = And(Item.price > 0, Item.stock > 0)
    assert evaluate(pred, _ctx(Item(price=10.0, stock=3))) is True
    assert evaluate(pred, _ctx(Item(price=10.0, stock=0))) is False


def test_evaluate_not():
    class Item(Entity):
        active: bool

    pred = Not(Item.active == False)  # noqa: E712
    assert evaluate(pred, _ctx(Item(active=True))) is True
    assert evaluate(pred, _ctx(Item(active=False))) is False


def test_evaluate_implies():
    class Hook(Entity):
        holds_cloak: bool

    class Player(Entity):
        has_cloak: bool

    pred = Implies(Hook.holds_cloak == True, Player.has_cloak == False)  # noqa: E712
    assert evaluate(pred, _ctx(Hook(holds_cloak=True), Player(has_cloak=False))) is True
    assert evaluate(pred, _ctx(Hook(holds_cloak=True), Player(has_cloak=True))) is False
    # vacuously true when the antecedent is false
    assert evaluate(pred, _ctx(Hook(holds_cloak=False), Player(has_cloak=True))) is True


# ── Invariant / Action / Scenario / Spec ──────────────────────────────────────


def test_invariant_holds_expression():
    class Wallet(Entity):
        balance: float

    inv = Invariant(Wallet.balance >= 0, label="No overdraft")
    assert isinstance(inv.expression, _Gte)
    assert inv.label == "No overdraft"


def test_action_pre_and_effect():
    class Order(Entity):
        status: str

    action = Action(
        id="pay",
        pre=[Order.status == "pending"],
        effect=[Set(Order.status, "paid")],
    )
    assert len(action.pre) == 1
    assert len(action.effect) == 1


def test_action_on_accepts_single_event():
    class Ping(Event):
        source: str

    action = Action(id="react", on=Ping)
    assert action.on == [Ping]


def test_scenario_given_and_expected():
    class Item(Entity):
        price: float

    action = Action(id="buy", pre=[Item.price > 0])
    sc = Scenario(
        id="sc1",
        name="Happy",
        action=action,
        given=[Item(price=5.0)],
        expected=Expect.PASS,
    )
    assert sc.expected == Expect.PASS
    assert len(sc.given) == 1
    assert isinstance(sc.given[0], Item)


def test_spec_aggregate():
    class Widget(Entity):
        value: int

    action = Action(id="make", pre=[Widget.value > 0])
    sc = Scenario(id="s", name="S", action=action, given=[Widget(value=1)], expected=Expect.PASS)
    spec = Spec(id="spec", name="Test", entities=[Widget], actions=[action], scenarios=[sc])
    assert spec.id == "spec"
    assert len(spec.scenarios) == 1


# ── Lifecycle ──────────────────────────────────────────────────────────────────


def test_lifecycle_reachable_states():
    class S(Enum):
        A = "a"
        B = "b"
        C = "c"
        D = "d"  # unreachable

    class Thing(Entity):
        state: S = Lifecycle(
            initial=S.A,
            transitions=[
                Transition(S.A, [S.B]),
                Transition(S.B, [S.C]),
            ],
        )

    lc = Thing.state.lifecycle
    assert lc is not None
    reachable = lc.reachable_states()
    assert S.A in reachable
    assert S.B in reachable
    assert S.C in reachable
    assert S.D not in reachable


def test_lifecycle_entity_cls():
    class Order(Entity):
        status: str = Lifecycle(initial="pending")

    lc = Order.status.lifecycle
    assert lc is not None
    assert lc.entity_cls is Order
    assert lc.field_name == "status"
    assert lc.field is Order.status


def test_transition_requires_a_collection():
    try:
        Transition("pending", "paid")
        assert False, "should have raised"
    except TypeError as exc:
        assert "must be a collection" in str(exc)


def test_structural_warns_unreachable_state_in_given():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Status(Enum):
        A = "a"
        B = "b"
        C = "c"  # no transition into C

    class Item(Entity):
        state: Status = Lifecycle(
            initial=Status.A,
            transitions=[Transition(Status.A, [Status.B])],
        )

    action = Action(id="act", pre=[Item.state == Status.A])
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Item(state=Status.C)],  # unreachable state
        expected=Expect.FAIL,
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Item],
        actions=[action],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert any("not reachable" in f.message for f in warnings)


def test_structural_transition_out_of_terminal_state_is_error():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Status(Enum):
        OPEN = "open"
        CLOSED = "closed"

    class Ticket(Entity):
        state: Status = Lifecycle(
            initial=Status.OPEN,
            transitions=[
                Transition(Status.OPEN, [Status.CLOSED]),
                Transition(Status.CLOSED, [Status.OPEN]),  # escapes a terminal state
            ],
            terminal=[Status.CLOSED],
        )

    spec = Spec(id="s", name="S", entities=[Ticket])
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("terminal" in f.message for f in errors)


def test_runner_blocks_modification_of_terminal_entity():
    from analint.validator.scenario_runner import run_scenario

    class Status(Enum):
        OPEN = "open"
        CLOSED = "closed"

    class Ticket(Entity):
        state: Status = Lifecycle(
            initial=Status.OPEN,
            transitions=[Transition(Status.OPEN, [Status.CLOSED])],
            terminal=[Status.CLOSED],
        )
        notes: int

    action = Action(id="annotate", effect=[Add(Ticket.notes, 1)])
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Ticket(state=Status.CLOSED, notes=0)],
        expected=Expect.FAIL,  # terminal entity must not be modifiable
    )
    spec = Spec(id="s", name="S", entities=[Ticket], actions=[action], scenarios=[sc])
    result = run_scenario(sc, spec)
    assert result.passed


# ── Actor ──────────────────────────────────────────────────────────────────────


def test_actor_subclass():
    class Customer(Actor):
        pass

    assert issubclass(Customer, Actor)


def test_action_with_actor():
    class Customer(Actor):
        pass

    action = Action(id="checkout", by=Customer)
    assert action.by is Customer


def test_structural_actor_not_registered():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Customer(Actor):
        pass

    class Item(Entity):
        price: float

    action = Action(id="act", by=Customer, pre=[Item.price > 0])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s",
        name="S",
        entities=[Item],
        actors=[],  # Customer not registered
        actions=[action],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("Customer" in f.message and "not in spec.actors" in f.message for f in errors)


def test_structural_actor_registered_ok():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Customer(Actor):
        pass

    class Item(Entity):
        price: float

    action = Action(id="act", by=Customer, pre=[Item.price > 0])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s",
        name="S",
        entities=[Item],
        actors=[Customer],
        actions=[action],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert not any("Customer" in f.message for f in errors)


# ── Event ──────────────────────────────────────────────────────────────────────


def test_event_field_access():
    class OrderPlaced(Event):
        order_id: str
        total: float

    assert isinstance(OrderPlaced.order_id, FieldDescriptor)
    assert OrderPlaced.order_id.field_name == "order_id"


def test_event_instance():
    class OrderPlaced(Event):
        order_id: str
        total: float

    ev = OrderPlaced(order_id="o1", total=50.0)
    assert ev.order_id == "o1"
    assert ev.total == 50.0


def test_structural_event_not_registered():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class OrderPlaced(Event):
        order_id: str

    class Item(Entity):
        price: float

    action = Action(id="act", pre=[Item.price > 0], emits=[OrderPlaced])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s",
        name="S",
        entities=[Item],
        events=[],  # OrderPlaced not registered
        actions=[action],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("OrderPlaced" in f.message and "not in spec.events" in f.message for f in errors)


def test_structural_event_emitted_but_unhandled_warns():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class OrderPlaced(Event):
        order_id: str

    class Item(Entity):
        price: float

    action = Action(id="act", pre=[Item.price > 0], emits=[OrderPlaced])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s",
        name="S",
        entities=[Item],
        events=[OrderPlaced],
        actions=[action],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert any("OrderPlaced" in f.message and "never triggers" in f.message for f in warnings)


def test_event_payload_template_binds_fields():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Card(Entity):
        id: str
        title: str

    class CardCreated(Event):
        card_id: str

    action = Action(id="create", pre=[Card.title != ""], emits=[CardCreated(card_id=Card.id)])
    handler = Action(id="notify", on=CardCreated, pre=[CardCreated.card_id != ""])
    sc1 = Scenario(id="sc1", name="S1", action=action, given=[Card(id="c1", title="t")])
    sc2 = Scenario(id="sc2", name="S2", action=handler, given=[CardCreated(card_id="c1")])
    spec = Spec(
        id="s",
        name="S",
        entities=[Card],
        events=[CardCreated],
        actions=[action, handler],
        scenarios=[sc1, sc2],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert not errors


def test_event_payload_type_mismatch_warns():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Card(Entity):
        id: str
        weight: float

    class CardWeighed(Event):
        weight: str  # wrong: bound to a float field

    action = Action(id="weigh", pre=[Card.weight > 0], emits=[CardWeighed(weight=Card.weight)])
    handler = Action(id="log", on=CardWeighed, pre=[])
    sc = Scenario(id="sc", name="S", action=action, given=[Card(id="c", weight=1.0)])
    spec = Spec(
        id="s",
        name="S",
        entities=[Card],
        events=[CardWeighed],
        actions=[action, handler],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert any("types differ" in f.message for f in warnings)


def test_scenario_runner_evaluates_event_payload_predicates():
    from analint.validator.scenario_runner import run_scenario

    class BigOrder(Event):
        total: float

    class Ledger(Entity):
        entries: int

    handler = Action(
        id="handle-big",
        on=BigOrder,
        pre=[BigOrder.total > 100],
        effect=[Add(Ledger.entries, 1)],
    )
    sc_big = Scenario(
        id="sc-big",
        name="big",
        action=handler,
        given=[BigOrder(total=500.0), Ledger(entries=0)],
        then=[Assert(Ledger.entries == 1)],
        expected=Expect.PASS,
    )
    sc_small = Scenario(
        id="sc-small",
        name="small",
        action=handler,
        given=[BigOrder(total=5.0), Ledger(entries=0)],
        expected=Expect.FAIL,
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Ledger],
        events=[BigOrder],
        actions=[handler],
        scenarios=[sc_big, sc_small],
    )
    assert run_scenario(sc_big, spec).passed
    assert run_scenario(sc_small, spec).passed  # correctly blocked


# ── Requires ──────────────────────────────────────────────────────────────────


def test_requires_valid():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Item(Entity):
        price: float

    a = Action(id="a", pre=[Item.price > 0])
    b = Action(id="b", pre=[Item.price > 0], requires=[a])
    sc_a = Scenario(id="sc_a", name="SA", action=a, given=[Item(price=5.0)], expected=Expect.PASS)
    sc_b = Scenario(id="sc_b", name="SB", action=b, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(id="s", name="S", entities=[Item], actions=[a, b], scenarios=[sc_a, sc_b])
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert not any("circular" in f.message for f in errors)


def test_requires_circular_detected():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Item(Entity):
        price: float

    a = Action(id="a", pre=[Item.price > 0])
    b = Action(id="b", pre=[Item.price > 0])
    object.__setattr__(a, "requires", [b])
    object.__setattr__(b, "requires", [a])
    sc_a = Scenario(id="sc_a", name="SA", action=a, given=[Item(price=5.0)], expected=Expect.PASS)
    sc_b = Scenario(id="sc_b", name="SB", action=b, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(id="s", name="S", entities=[Item], actions=[a, b], scenarios=[sc_a, sc_b])
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("circular" in f.message for f in errors)


# ── Effects ───────────────────────────────────────────────────────────────────


def _spec_for(action, *, entities, scenarios, lifecycles=()):
    return Spec(
        id="s",
        name="S",
        entities=list(entities),
        actions=[action],
        scenarios=list(scenarios),
        lifecycles=list(lifecycles),
    )


def test_effect_set_changes_state():
    from analint.validator.scenario_runner import run_scenario

    class Order(Entity):
        status: str

    action = Action(
        id="pay",
        pre=[Order.status == "pending"],
        effect=[Set(Order.status, "paid")],
        post=[Order.status == "paid"],
    )
    sc = Scenario(
        id="sc", name="SC", action=action, given=[Order(status="pending")], expected=Expect.PASS
    )
    result = run_scenario(sc, _spec_for(action, entities=[Order], scenarios=[sc]))
    assert result.passed


def test_effect_subtract():
    from analint.validator.scenario_runner import run_scenario

    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    action = Action(
        id="pay",
        pre=[Wallet.balance >= Order.total],
        effect=[Subtract(Wallet.balance, Order.total)],
    )
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Wallet(balance=100.0), Order(total=30.0)],
        then=[Assert(Wallet.balance == 70.0)],
        expected=Expect.PASS,
    )
    result = run_scenario(sc, _spec_for(action, entities=[Wallet, Order], scenarios=[sc]))
    assert result.passed


def test_effects_are_simultaneous():
    """Right-hand sides are resolved against the pre-state, not the partial post-state."""
    from analint.validator.scenario_runner import run_scenario

    class Order(Entity):
        status: str

    class Audit(Entity):
        last_status: str

    action = Action(
        id="pay",
        effect=[
            Set(Order.status, "paid"),
            Set(Audit.last_status, Order.status),  # must observe the OLD status
        ],
    )
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Order(status="pending"), Audit(last_status="")],
        then=[
            Assert(Order.status == "paid"),
            Assert(Audit.last_status == "pending"),
        ],
        expected=Expect.PASS,
    )
    result = run_scenario(sc, _spec_for(action, entities=[Order, Audit], scenarios=[sc]))
    assert result.passed, [f.message for f in result.findings]


def test_structural_conflicting_effects_on_same_field():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Wallet(Entity):
        balance: float

    action = Action(
        id="weird",
        effect=[
            Set(Wallet.balance, 0.0),
            Subtract(Wallet.balance, 5.0),
        ],
    )
    sc = Scenario(id="sc", name="SC", action=action, given=[Wallet(balance=10.0)])
    spec = _spec_for(action, entities=[Wallet], scenarios=[sc])
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("simultaneous" in f.message for f in errors)


def test_invariant_checked_after_effects():
    """A world invariant violated by the post-state must fail the scenario."""
    from analint.validator.scenario_runner import run_scenario

    class Wallet(Entity):
        balance: float

    no_overdraft = Invariant(Wallet.balance >= 0, label="No overdraft", id="no-overdraft")
    action = Action(id="spend", effect=[Subtract(Wallet.balance, 100.0)])
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Wallet(balance=10.0)],  # 10 - 100 = -90 → invariant breaks post
        expected=Expect.PASS,
    )
    spec = Spec(
        id="s",
        name="S",
        entities=[Wallet],
        invariants=[no_overdraft],
        actions=[action],
        scenarios=[sc],
    )
    result = run_scenario(sc, spec)
    assert not result.passed
    assert any("INVARIANT (post)" in f.message for f in result.findings)


def test_then_assert_fails_when_condition_wrong():
    from analint.validator.scenario_runner import run_scenario

    class Order(Entity):
        status: str

    action = Action(
        id="pay",
        pre=[Order.status == "pending"],
        effect=[Set(Order.status, "paid")],
    )
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Order(status="pending")],
        then=[Assert(Order.status == "cancelled")],  # wrong: it becomes "paid"
        expected=Expect.PASS,
    )
    result = run_scenario(sc, _spec_for(action, entities=[Order], scenarios=[sc]))
    assert not result.passed


def test_then_emitted_ok():
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        price: float

    class ItemSold(Event):
        item_id: str

    action = Action(id="sell", pre=[Item.price > 0], emits=[ItemSold(item_id=Item.price)])
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Item(price=10.0)],
        then=[Emitted(ItemSold)],
        expected=Expect.PASS,
    )
    result = run_scenario(sc, _spec_for(action, entities=[Item], scenarios=[sc]))
    assert result.passed


def test_then_emitted_fails_when_not_in_emits():
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        price: float

    class OtherEvent(Event):
        x: str

    action = Action(id="sell", pre=[Item.price > 0], emits=[])
    sc = Scenario(
        id="sc",
        name="SC",
        action=action,
        given=[Item(price=10.0)],
        then=[Emitted(OtherEvent)],
        expected=Expect.PASS,
    )
    result = run_scenario(sc, _spec_for(action, entities=[Item], scenarios=[sc]))
    assert not result.passed


# ── Flow ──────────────────────────────────────────────────────────────────────


def test_flow_requires_order_valid():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Item(Entity):
        price: float

    a = Action(id="a", pre=[Item.price > 0])
    b = Action(id="b", pre=[Item.price > 0], requires=[a])
    flow = Flow(id="f1", steps=[a, b])
    sc_a = Scenario(id="sc_a", name="SA", action=a, given=[Item(price=5.0)])
    sc_b = Scenario(id="sc_b", name="SB", action=b, given=[Item(price=5.0)])
    spec = Spec(
        id="s", name="S", entities=[Item], actions=[a, b], flows=[flow], scenarios=[sc_a, sc_b]
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR and "requires" in f.message]
    assert not errors


def test_flow_requires_order_violated():
    from analint.reporter.base import Severity
    from analint.validator.structural import validate_structural

    class Item(Entity):
        price: float

    a = Action(id="a", pre=[Item.price > 0])
    b = Action(id="b", pre=[Item.price > 0], requires=[a])
    flow = Flow(id="f1", steps=[b, a])  # wrong order: b before a
    sc_a = Scenario(id="sc_a", name="SA", action=a, given=[Item(price=5.0)])
    sc_b = Scenario(id="sc_b", name="SB", action=b, given=[Item(price=5.0)])
    spec = Spec(
        id="s", name="S", entities=[Item], actions=[a, b], flows=[flow], scenarios=[sc_a, sc_b]
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("requires" in f.message and "'a'" in f.message for f in errors)


# ── Loader: id autofill from variable names ───────────────────────────────────


def test_collect_fills_ids_from_variable_names():
    import types

    from analint.loader.python_loader import collect_from_modules

    class Item(Entity):
        price: float

    module = types.ModuleType("fake_spec_module")
    module.buy_item = Action(pre=[Item.price > 0])
    module.price_positive = Invariant(Item.price > 0)
    collected = collect_from_modules([module])

    assert collected["actions"][0].id == "buy_item"
    assert collected["invariants"][0].id == "price_positive"
