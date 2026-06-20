"""The saga properties. The key one is `settlement_always_reachable`: from
every reachable state the order can *still reach* one of the consistent
terminal constellations — i.e. no reachable state is a dead end with money or
goods stuck. This is recoverability (a settlement always stays reachable), not
liveness: it does not claim every run inevitably finishes."""

from analint import And, DeadActions, NoDeadEnd, Or, Reachable, Unreachable

from .entities import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Reservation,
    ReservationStatus,
)

# The consistent terminal states the order can settle into.
_settled = Or(
    # delivered and paid for
    And(
        Order.status == OrderStatus.DELIVERED,
        Payment.status == PaymentStatus.CAPTURED,
        Reservation.status == ReservationStatus.CONSUMED,
    ),
    # rejected before anything happened
    And(
        Order.status == OrderStatus.CANCELLED,
        Payment.status == PaymentStatus.NONE,
        Reservation.status == ReservationStatus.NONE,
    ),
    # payment failed → stock returned, nothing charged
    And(
        Order.status == OrderStatus.CANCELLED,
        Payment.status == PaymentStatus.FAILED,
        Reservation.status == ReservationStatus.RELEASED,
    ),
    # cancelled / lost → refunded (goods back on the shelf or written off)
    And(
        Order.status == OrderStatus.CANCELLED,
        Payment.status == PaymentStatus.REFUNDED,
        Reservation.status == ReservationStatus.RELEASED,
    ),
    And(
        Order.status == OrderStatus.CANCELLED,
        Payment.status == PaymentStatus.REFUNDED,
        Reservation.status == ReservationStatus.CONSUMED,
    ),
)

settlement_always_reachable = NoDeadEnd(
    goal=_settled,
    label="from any state the order can still settle consistently",
)

happy_path_exists = Reachable(
    And(Order.status == OrderStatus.DELIVERED, Payment.status == PaymentStatus.CAPTURED),
    label="an order can be delivered and paid",
)

refund_path_exists = Reachable(
    And(Order.status == OrderStatus.CANCELLED, Payment.status == PaymentStatus.REFUNDED),
    label="a cancellation with refund is possible",
)

no_free_goods = Unreachable(
    And(Order.status == OrderStatus.DELIVERED, Payment.status != PaymentStatus.CAPTURED),
    label="goods are never delivered unpaid",
)

no_money_for_nothing = Unreachable(
    And(Order.status == OrderStatus.CANCELLED, Payment.status == PaymentStatus.CAPTURED),
    label="a cancelled order never keeps captured money",
)

every_step_used = DeadActions()
