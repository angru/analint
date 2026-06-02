from enum import Enum

from analint import (
    Actor, Add, And, Assert, BusinessRule, Emitted, Entity, Event, Expect,
    Flow, Not, Or, RuleType, Scenario, Set, Spec, StateMachine,
    Subtract, Transition, UseCase,
)
from analint.models.predicate import _And, _Eq, _Gt, _Gte, _Not, _Or
from analint.models.entity import FieldDescriptor
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


def test_entity_missing_required_field_raises():
    class Item(Entity):
        price: float

    try:
        Item()
        assert False, "should have raised"
    except TypeError as e:
        assert "price" in str(e)


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


# ── BusinessRule / UseCase / Scenario / Spec ──────────────────────────────────

def test_business_rule_with_expression():
    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    rule = BusinessRule(
        id="r1",
        name="Sufficient funds",
        expression=Wallet.balance >= Order.total,
    )
    assert rule.id == "r1"
    assert isinstance(rule.expression, _Gte)


def test_scenario_given_and_expected():
    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", entities=[Item], rules=[rule])
    sc = Scenario(
        id="sc1",
        name="Happy",
        use_case=uc,
        given=[Item(price=5.0)],
        expected=Expect.PASS,
    )
    assert sc.expected == Expect.PASS
    assert len(sc.given) == 1
    assert isinstance(sc.given[0], Item)


def test_spec_aggregate():
    class Widget(Entity):
        value: int

    rule = BusinessRule(id="r", name="R", expression=Widget.value > 0)
    uc = UseCase(id="uc", name="UC", entities=[Widget], rules=[rule])
    sc = Scenario(id="s", name="S", use_case=uc, given=[Widget(value=1)], expected=Expect.PASS)
    spec = Spec(id="spec", name="Test", entities=[Widget], rules=[rule], use_cases=[uc], scenarios=[sc])
    assert spec.id == "spec"
    assert len(spec.scenarios) == 1


# ── StateMachine ───────────────────────────────────────────────────────────────

def test_state_machine_reachable_states():
    from enum import Enum

    class S(Enum):
        A = "a"
        B = "b"
        C = "c"
        D = "d"  # недостижимо

    class Thing(Entity):
        state: S

    uc = UseCase(id="uc", name="UC")
    sm = StateMachine(
        id="sm",
        field=Thing.state,
        initial=S.A,
        transitions=[
            Transition(S.A, S.B),
            Transition(S.B, S.C),
        ],
    )
    reachable = sm.reachable_states()
    assert S.A in reachable
    assert S.B in reachable
    assert S.C in reachable
    assert S.D not in reachable


def test_state_machine_entity_cls():
    class Order(Entity):
        status: str

    sm = StateMachine(id="sm", field=Order.status, initial="pending", transitions=[])
    assert sm.entity_cls is Order
    assert sm.field_name == "status"


def test_structural_warns_unreachable_state_in_given():
    from enum import Enum
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Status(Enum):
        A = "a"
        B = "b"
        C = "c"  # нет перехода в C

    class Item(Entity):
        state: Status

    rule = BusinessRule(id="r", name="R", expression=Item.state == Status.A)
    uc = UseCase(id="uc", name="UC", entities=[Item], rules=[rule])
    sm = StateMachine(
        id="sm",
        field=Item.state,
        initial=Status.A,
        transitions=[Transition(Status.A, Status.B)],
        # Status.C недостижим
    )
    sc = Scenario(
        id="sc",
        name="SC",
        use_case=uc,
        given=[Item(state=Status.C)],  # недостижимый статус
        expected=Expect.FAIL,
    )
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        state_machines=[sm],
        rules=[rule],
        use_cases=[uc],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert any("not reachable" in f.message for f in warnings)


# ── Actor ──────────────────────────────────────────────────────────────────────

def test_actor_subclass():
    class Customer(Actor):
        pass

    assert issubclass(Customer, Actor)


def test_use_case_with_actor():
    class Customer(Actor):
        pass

    uc = UseCase(id="uc", name="Checkout", actor=Customer)
    assert uc.actor is Customer


def test_structural_actor_not_registered():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Customer(Actor):
        pass

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", actor=Customer, entities=[Item], rules=[rule])
    sc = Scenario(id="sc", name="SC", use_case=uc, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        actors=[],  # Customer not registered
        rules=[rule],
        use_cases=[uc],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("Customer" in f.message and "not in spec.actors" in f.message for f in errors)


def test_structural_actor_registered_ok():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Customer(Actor):
        pass

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", actor=Customer, entities=[Item], rules=[rule])
    sc = Scenario(id="sc", name="SC", use_case=uc, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        actors=[Customer],
        rules=[rule],
        use_cases=[uc],
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


def test_event_repr():
    class OrderPlaced(Event):
        order_id: str

    ev = OrderPlaced(order_id="o1")
    assert "OrderPlaced" in repr(ev)
    assert "o1" in repr(ev)


def test_structural_event_not_registered():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class OrderPlaced(Event):
        order_id: str

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", entities=[Item], rules=[rule], emits=[OrderPlaced])
    sc = Scenario(id="sc", name="SC", use_case=uc, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        events=[],  # OrderPlaced not registered
        rules=[rule],
        use_cases=[uc],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("OrderPlaced" in f.message and "not in spec.events" in f.message for f in errors)


def test_structural_event_emitted_but_unhandled_warns():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class OrderPlaced(Event):
        order_id: str

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", entities=[Item], rules=[rule], emits=[OrderPlaced])
    sc = Scenario(id="sc", name="SC", use_case=uc, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        events=[OrderPlaced],
        rules=[rule],
        use_cases=[uc],
        scenarios=[sc],
    )
    findings = validate_structural(spec)
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert any("OrderPlaced" in f.message and "never triggers" in f.message for f in warnings)


# ── Requires ──────────────────────────────────────────────────────────────────

def test_requires_valid():
    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc_a = UseCase(id="uc_a", name="A", entities=[Item], rules=[rule])
    uc_b = UseCase(id="uc_b", name="B", entities=[Item], rules=[rule], requires=[uc_a])
    sc_a = Scenario(id="sc_a", name="SA", use_case=uc_a, given=[Item(price=5.0)], expected=Expect.PASS)
    sc_b = Scenario(id="sc_b", name="SB", use_case=uc_b, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        rules=[rule],
        use_cases=[uc_a, uc_b],
        scenarios=[sc_a, sc_b],
    )
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert not any("circular" in f.message for f in errors)


def test_requires_circular_detected():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc_a = UseCase(id="uc_a", name="A", entities=[Item], rules=[rule])
    uc_b = UseCase(id="uc_b", name="B", entities=[Item], rules=[rule])
    # Manually inject circular dependency (pydantic allows Any)
    object.__setattr__(uc_a, "requires", [uc_b])
    object.__setattr__(uc_b, "requires", [uc_a])
    sc_a = Scenario(id="sc_a", name="SA", use_case=uc_a, given=[Item(price=5.0)], expected=Expect.PASS)
    sc_b = Scenario(id="sc_b", name="SB", use_case=uc_b, given=[Item(price=5.0)], expected=Expect.PASS)
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        rules=[rule],
        use_cases=[uc_a, uc_b],
        scenarios=[sc_a, sc_b],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("circular" in f.message for f in errors)


# ── Effects ───────────────────────────────────────────────────────────────────

def test_effect_set_changes_state():
    from analint.validator.scenario_runner import run_scenario

    class Order(Entity):
        status: str

    rule = BusinessRule(id="r", name="R", rule_type=RuleType.PRECONDITION,
                        expression=Order.status == "pending")
    rule_post = BusinessRule(id="rp", name="RP", rule_type=RuleType.POSTCONDITION,
                             expression=Order.status == "paid")
    uc = UseCase(
        id="uc", name="Pay",
        entities=[Order],
        rules=[rule, rule_post],
        effects=[Set(Order.status, "paid")],
    )
    sc = Scenario(id="sc", name="SC", use_case=uc, given=[Order(status="pending")],
                  expected=Expect.PASS)

    class FakeSpec:
        flows = []

    result = run_scenario(sc, FakeSpec())
    assert result.passed


def test_effect_subtract():
    from analint.validator.scenario_runner import run_scenario

    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    rule = BusinessRule(id="r", name="R", rule_type=RuleType.PRECONDITION,
                        expression=Wallet.balance >= Order.total)
    uc = UseCase(
        id="uc", name="Pay",
        entities=[Wallet, Order],
        rules=[rule],
        effects=[Subtract(Wallet.balance, Order.total)],
    )
    sc = Scenario(
        id="sc", name="SC",
        use_case=uc,
        given=[Wallet(balance=100.0), Order(total=30.0)],
        then=[Assert(Wallet.balance == 70.0)],
        expected=Expect.PASS,
    )

    class FakeSpec:
        flows = []

    result = run_scenario(sc, FakeSpec())
    assert result.passed


def test_then_assert_fails_when_condition_wrong():
    from analint.validator.scenario_runner import run_scenario

    class Order(Entity):
        status: str

    rule = BusinessRule(id="r", name="R", rule_type=RuleType.PRECONDITION,
                        expression=Order.status == "pending")
    uc = UseCase(
        id="uc", name="Pay",
        entities=[Order],
        rules=[rule],
        effects=[Set(Order.status, "paid")],
    )
    sc = Scenario(
        id="sc", name="SC",
        use_case=uc,
        given=[Order(status="pending")],
        then=[Assert(Order.status == "cancelled")],  # wrong: it becomes "paid"
        expected=Expect.PASS,
    )

    class FakeSpec:
        flows = []

    result = run_scenario(sc, FakeSpec())
    assert not result.passed


def test_then_emitted_ok():
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        price: float

    class ItemSold(Event):
        item_id: str

    rule = BusinessRule(id="r", name="R", rule_type=RuleType.PRECONDITION,
                        expression=Item.price > 0)
    uc = UseCase(id="uc", name="Sell", entities=[Item], rules=[rule], emits=[ItemSold])
    sc = Scenario(
        id="sc", name="SC",
        use_case=uc,
        given=[Item(price=10.0)],
        then=[Emitted(ItemSold)],
        expected=Expect.PASS,
    )

    class FakeSpec:
        flows = []

    result = run_scenario(sc, FakeSpec())
    assert result.passed


def test_then_emitted_fails_when_not_in_emits():
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        price: float

    class OtherEvent(Event):
        x: str

    rule = BusinessRule(id="r", name="R", rule_type=RuleType.PRECONDITION,
                        expression=Item.price > 0)
    uc = UseCase(id="uc", name="Sell", entities=[Item], rules=[rule], emits=[])
    sc = Scenario(
        id="sc", name="SC",
        use_case=uc,
        given=[Item(price=10.0)],
        then=[Emitted(OtherEvent)],
        expected=Expect.PASS,
    )

    class FakeSpec:
        flows = []

    result = run_scenario(sc, FakeSpec())
    assert not result.passed


# ── Flow ──────────────────────────────────────────────────────────────────────

def test_flow_requires_order_valid():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc_a = UseCase(id="uc_a", name="A", entities=[Item], rules=[rule])
    uc_b = UseCase(id="uc_b", name="B", entities=[Item], rules=[rule], requires=[uc_a])
    flow = Flow(id="f1", steps=[uc_a, uc_b])
    sc_a = Scenario(id="sc_a", name="SA", use_case=uc_a, given=[Item(price=5.0)])
    sc_b = Scenario(id="sc_b", name="SB", use_case=uc_b, given=[Item(price=5.0)])
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        rules=[rule],
        use_cases=[uc_a, uc_b],
        flows=[flow],
        scenarios=[sc_a, sc_b],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR and "requires" in f.message]
    assert not errors


def test_flow_requires_order_violated():
    from analint.validator.structural import validate_structural
    from analint.reporter.base import Severity

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc_a = UseCase(id="uc_a", name="A", entities=[Item], rules=[rule])
    uc_b = UseCase(id="uc_b", name="B", entities=[Item], rules=[rule], requires=[uc_a])
    flow = Flow(id="f1", steps=[uc_b, uc_a])  # wrong order: B before A
    sc_a = Scenario(id="sc_a", name="SA", use_case=uc_a, given=[Item(price=5.0)])
    sc_b = Scenario(id="sc_b", name="SB", use_case=uc_b, given=[Item(price=5.0)])
    spec = Spec(
        id="s", name="S",
        entities=[Item],
        rules=[rule],
        use_cases=[uc_a, uc_b],
        flows=[flow],
        scenarios=[sc_a, sc_b],
    )
    findings = validate_structural(spec)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert any("requires" in f.message and "uc_a" in f.message for f in errors)
