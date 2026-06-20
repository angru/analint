from enum import StrEnum

from analint import (
    Action,
    Emitted,
    Entity,
    Event,
    Expect,
    Field,
    Lifecycle,
    Reachable,
    Scenario,
    Set,
    Spec,
    Subtract,
)

# ── Domain entity statuses ─────────────────────────────────────────────────────


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


# ── Domain entities ────────────────────────────────────────────────────────────


class Order(Entity):
    id: str
    status: OrderStatus = Lifecycle(
        initial=OrderStatus.PENDING,
        transitions={
            OrderStatus.PENDING: [OrderStatus.PAID, OrderStatus.CANCELLED],
            OrderStatus.PAID: [OrderStatus.CANCELLED],
        },
        terminal=[OrderStatus.CANCELLED],
        description="An order can be paid and later cancelled",
    )
    total: float = Field(gt=0)
    customer_id: str


class Wallet(Entity):
    balance: float = Field(ge=0)
    customer_id: str


class Product(Entity):
    stock: int = Field(ge=0)
    price: float = Field(gt=0)
    name: str


# ── Events ─────────────────────────────────────────────────────────────────────


class OrderPlaced(Event):
    order_id: str
    total: float
    customer_id: str


# ── Actions ────────────────────────────────────────────────────────────────────

checkout = Action(
    name="Customer Checkout",
    description="Customer places an order; all preconditions must hold",
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
        Order.status == OrderStatus.PAID,
        Wallet.balance == 50.0,
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
        Wallet(balance=10.0, customer_id="c1"),  # 10 < 50 → blocked
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
        Product(stock=0, price=50.0, name="Widget"),  # stock=0 → blocked
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

# ── Reachability ───────────────────────────────────────────────────────────────

# Entities here have required fields without defaults, so the query supplies
# the initial world explicitly via given=[...].
paid_is_reachable = Reachable(
    Order.status == OrderStatus.PAID,
    given=[
        Order(id="o1", total=50.0, customer_id="c1"),
        Wallet(balance=100.0, customer_id="c1"),
        Product(stock=5, price=50.0, name="Widget"),
    ],
    label="an order can actually get paid",
)

# ── Spec — everything above is discovered automatically ───────────────────────

spec = Spec(
    id="ecommerce",
    name="E-commerce Platform",
    version="0.9.0",
    description="Online store — business behaviour spec",
)
