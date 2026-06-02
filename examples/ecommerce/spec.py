from enum import Enum

from analint import (
    Actor, Add, And, Assert, BusinessRule, Emitted, Entity, Event, Expect,
    Flow, Not, Or, RuleType, Scenario, Set, Spec, StateMachine,
    Subtract, Transition, UseCase,
)

# ── Actors ─────────────────────────────────────────────────────────────────────


class Customer(Actor):
    pass


class Admin(Actor):
    pass


# ── Domain entity statuses ─────────────────────────────────────────────────────


class OrderStatus(Enum):
    PENDING   = "pending"
    PAID      = "paid"
    CANCELLED = "cancelled"


class PaymentMethod(Enum):
    CARD   = "card"
    WALLET = "wallet"


# ── Domain entities ────────────────────────────────────────────────────────────


class Order(Entity):
    status: OrderStatus = OrderStatus.PENDING
    total: float
    customer_id: str


class Wallet(Entity):
    balance: float
    customer_id: str


class Product(Entity):
    stock: int
    price: float
    name: str


# ── Events ─────────────────────────────────────────────────────────────────────


class OrderPlaced(Event):
    order_id: str
    total: float
    customer_id: str


# ── Business rules ─────────────────────────────────────────────────────────────

rule_price_positive = BusinessRule(
    id="price-positive",
    name="Product price must be positive",
    rule_type=RuleType.INVARIANT,
    expression=Product.price > 0,
)

rule_funds = BusinessRule(
    id="sufficient-funds",
    name="Wallet balance must cover order total",
    rule_type=RuleType.PRECONDITION,
    expression=Wallet.balance >= Order.total,
)

rule_stock = BusinessRule(
    id="stock-available",
    name="Product must have stock",
    rule_type=RuleType.PRECONDITION,
    expression=Product.stock > 0,
)

rule_order_pending = BusinessRule(
    id="order-pending",
    name="Order must be in pending status to check out",
    rule_type=RuleType.PRECONDITION,
    expression=Order.status == OrderStatus.PENDING,
)

rule_order_paid = BusinessRule(
    id="order-paid",
    name="Order must be paid after checkout",
    rule_type=RuleType.POSTCONDITION,
    expression=Order.status == OrderStatus.PAID,
)

# ── Use cases ──────────────────────────────────────────────────────────────────

uc_checkout = UseCase(
    id="checkout",
    name="Customer Checkout",
    description="Customer places an order; all preconditions must hold",
    actor=Customer,
    entities=[Order, Wallet, Product],
    rules=[rule_funds, rule_stock, rule_price_positive, rule_order_pending, rule_order_paid],
    emits=[OrderPlaced],
    effects=[
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),
        Subtract(Product.stock, 1),
    ],
)

# ── Scenarios ──────────────────────────────────────────────────────────────────

sc_happy = Scenario(
    id="checkout/happy",
    name="Successful purchase",
    use_case=uc_checkout,
    given=[
        Order(total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],
    then=[
        Assert(Order.status == OrderStatus.PAID),
        Assert(Wallet.balance == 50.0),
        Emitted(OrderPlaced),
    ],
    expected=Expect.PASS,
)

sc_no_funds = Scenario(
    id="checkout/no-funds",
    name="Insufficient wallet balance",
    use_case=uc_checkout,
    given=[
        Order(total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=10.0, customer_id="c1"),          # 10 < 50 → rule_funds fails
        Product(stock=5, price=50.0, name="Widget"),
    ],
    expected=Expect.FAIL,
)

sc_no_stock = Scenario(
    id="checkout/out-of-stock",
    name="Product out of stock",
    use_case=uc_checkout,
    given=[
        Order(total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=0, price=50.0, name="Widget"),     # stock=0 → rule_stock fails
    ],
    expected=Expect.FAIL,
)

sc_already_paid = Scenario(
    id="checkout/already-paid",
    name="Order already paid — cannot check out again",
    use_case=uc_checkout,
    given=[
        Order(total=50.0, status=OrderStatus.PAID, customer_id="c1"),  # wrong status
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],
    expected=Expect.FAIL,
)

# ── State machines ─────────────────────────────────────────────────────────────

order_lifecycle = StateMachine(
    id="order-lifecycle",
    field=Order.status,
    initial=OrderStatus.PENDING,
    transitions=[
        Transition(OrderStatus.PENDING, [OrderStatus.PAID, OrderStatus.CANCELLED]),
        Transition(OrderStatus.PAID,    OrderStatus.CANCELLED),
    ],
    description="Order moves from PENDING to PAID on checkout, can be cancelled at any point",
)

# ── Spec ───────────────────────────────────────────────────────────────────────

spec = Spec(
    id="ecommerce",
    name="E-commerce Platform",
    version="0.5.0",
    description="Online store — business analytics spec",
    entities=[Order, Wallet, Product],
    actors=[Customer, Admin],
    events=[OrderPlaced],
    state_machines=[order_lifecycle],
    rules=[rule_funds, rule_stock, rule_price_positive, rule_order_pending, rule_order_paid],
    use_cases=[uc_checkout],
    scenarios=[sc_happy, sc_no_funds, sc_no_stock, sc_already_paid],
)
