"""Negative control appended to the cancellation what-if by the trial runner.

This alternative action is deliberately absent from both successful flows.
Their PASS must not hide the safety violation found by property exploration.
"""

from fulfillment.entities import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Shipment,
    ShipmentStatus,
)

from analint import Action, Set

cancel_without_refund = Action(
    id="cancel_without_refund",
    pre=[
        Order.status == OrderStatus.SHIPPED,
        Shipment.status == ShipmentStatus.DISPATCHED,
        Payment.status == PaymentStatus.CAPTURED,
    ],
    effect=[Set(Order.status, OrderStatus.CANCELLED)],
)
