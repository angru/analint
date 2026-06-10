from enum import Enum

from analint import (
    Action, Actor, Assert, Emitted, Entity, Event, Expect,
    Invariant, Lifecycle, Scenario, Set, Spec, Subtract, Transition,
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


# ── Domain entities ────────────────────────────────────────────────────────────


class Order(Entity):
    id: str
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


# ── Invariants (hold in every state) ───────────────────────────────────────────

price_is_positive = Invariant(
    Product.price > 0,
    label="Product price must be positive",
)

balance_not_negative = Invariant(
    Wallet.balance >= 0,
    label="Wallet balance can never go below zero",
)

# ── Actions ────────────────────────────────────────────────────────────────────

checkout = Action(
    name="Customer Checkout",
    description="Customer places an order; all preconditions must hold",
    by=Customer,
    pre=[
        Wallet.balance >= Order.total,
        Product.stock > 0,
        Order.status == OrderStatus.PENDING,
    ],
    effect=[
        Set(Order.status, OrderStatus.PAID),
        Subtract(Wallet.balance, Order.total),
        Subtract(Product.stock, 1),
    ],
    post=[
        Order.status == OrderStatus.PAID,
    ],
    emits=[
        OrderPlaced(order_id=Order.id, total=Order.total, customer_id=Order.customer_id),
    ],
)

# ── Scenarios ──────────────────────────────────────────────────────────────────

sc_happy = Scenario(
    id="checkout/happy",
    name="Successful purchase",
    action=checkout,
    given=[
        Order(id="o1", total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
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
    action=checkout,
    given=[
        Order(id="o1", total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=10.0, customer_id="c1"),          # 10 < 50 → blocked
        Product(stock=5, price=50.0, name="Widget"),
    ],
    expected=Expect.FAIL,
)

sc_no_stock = Scenario(
    id="checkout/out-of-stock",
    name="Product out of stock",
    action=checkout,
    given=[
        Order(id="o1", total=50.0, status=OrderStatus.PENDING, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=0, price=50.0, name="Widget"),     # stock=0 → blocked
    ],
    expected=Expect.FAIL,
)

sc_already_paid = Scenario(
    id="checkout/already-paid",
    name="Order already paid — cannot check out again",
    action=checkout,
    given=[
        Order(id="o1", total=50.0, status=OrderStatus.PAID, customer_id="c1"),  # wrong status
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],
    expected=Expect.FAIL,
)

# ── Lifecycles ─────────────────────────────────────────────────────────────────

order_lifecycle = Lifecycle(
    field=Order.status,
    initial=OrderStatus.PENDING,
    transitions=[
        Transition(OrderStatus.PENDING, [OrderStatus.PAID, OrderStatus.CANCELLED]),
        Transition(OrderStatus.PAID,    OrderStatus.CANCELLED),
    ],
    terminal=[OrderStatus.CANCELLED],
    description="Order moves from PENDING to PAID on checkout, can be cancelled at any point",
)

# ── Spec — everything above is discovered automatically ───────────────────────

spec = Spec(
    id="ecommerce",
    name="E-commerce Platform",
    version="0.9.0",
    description="Online store — business behaviour spec",
)
