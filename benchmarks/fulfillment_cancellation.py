"""Additive what-if: cancellation while dispatched atomically refunds payment.

Run against examples/fulfillment. This is a finite client-policy experiment:
physical returns, provider latency and inevitable completion are not modelled.
"""

from fulfillment.actions import (
    authorize_payment,
    capture_payment,
    confirm_delivery,
    confirm_order,
    dispatch,
    reserve_stock,
    supplier_restock,
)
from fulfillment.entities import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Reservation,
    ReservationStatus,
    Shipment,
    ShipmentStatus,
    Warehouse,
)

from analint import Action, And, Assert, Expect, Flow, Reachable, Scenario, Set

# BEGIN NEW ACTION: the runner substitutes the old cancellation for its probe.
cancel_after_dispatch = Action(
    id="cancel_after_dispatch",
    name="Cancel an in-transit order and refund its captured payment",
    pre=[
        Order.status == OrderStatus.SHIPPED,
        Shipment.status == ShipmentStatus.DISPATCHED,
        Payment.status == PaymentStatus.CAPTURED,
    ],
    effect=[
        Set(Order.status, OrderStatus.CANCELLED),
        Set(Payment.status, PaymentStatus.REFUNDED),
    ],
)
# END NEW ACTION

cancel_dispatched = Scenario(
    id="cancel_dispatched",
    action=cancel_after_dispatch,
    given=[
        Order(status=OrderStatus.SHIPPED),
        Payment(status=PaymentStatus.CAPTURED),
        Reservation(status=ReservationStatus.CONSUMED),
        Shipment(status=ShipmentStatus.DISPATCHED),
        Warehouse(stock=0),
    ],
    then=[Order.status == OrderStatus.CANCELLED, Payment.status == PaymentStatus.REFUNDED],
)

reject_delivered_cancellation = Scenario(
    id="reject_delivered_cancellation",
    action=cancel_after_dispatch,
    given=[
        Order(status=OrderStatus.DELIVERED),
        Payment(status=PaymentStatus.CAPTURED),
        Reservation(status=ReservationStatus.CONSUMED),
        Shipment(status=ShipmentStatus.DELIVERED),
        Warehouse(stock=0),
    ],
    expected=Expect.FAIL,
)

cancel_in_transit = Flow(
    id="cancel_in_transit",
    given=[Order(), Payment(), Reservation(), Shipment(), Warehouse()],
    steps=[
        supplier_restock,
        reserve_stock,
        authorize_payment,
        confirm_order,
        capture_payment,
        dispatch,
        cancel_after_dispatch,
        Assert(Order.status == OrderStatus.CANCELLED),
        Assert(Payment.status == PaymentStatus.REFUNDED),
        Assert(Reservation.status == ReservationStatus.CONSUMED),
        Assert(Warehouse.stock == 0),
    ],
)

deliver_normally = Flow(
    id="deliver_normally",
    given=[Order(), Payment(), Reservation(), Shipment(), Warehouse()],
    steps=[
        supplier_restock,
        reserve_stock,
        authorize_payment,
        confirm_order,
        capture_payment,
        dispatch,
        confirm_delivery,
        Assert(Order.status == OrderStatus.DELIVERED),
        Assert(Payment.status == PaymentStatus.CAPTURED),
    ],
)

in_transit_refund_exists = Reachable(
    And(
        Order.status == OrderStatus.CANCELLED,
        Payment.status == PaymentStatus.REFUNDED,
        Shipment.status == ShipmentStatus.DISPATCHED,
    ),
    id="in_transit_refund_exists",
)
