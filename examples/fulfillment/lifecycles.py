from analint import Lifecycle, Transition
from .entities import (
    Order, OrderStatus, Payment, PaymentStatus, Reservation, ReservationStatus,
    Shipment, ShipmentStatus,
)

order_lifecycle = Lifecycle(
    field=Order.status,
    initial=OrderStatus.PLACED,
    transitions=[
        Transition(OrderStatus.PLACED,    [OrderStatus.CONFIRMED, OrderStatus.CANCELLED]),
        Transition(OrderStatus.CONFIRMED, [OrderStatus.SHIPPED, OrderStatus.CANCELLED]),
        Transition(OrderStatus.SHIPPED,   [OrderStatus.DELIVERED, OrderStatus.CANCELLED]),
    ],
    terminal=[OrderStatus.DELIVERED, OrderStatus.CANCELLED],
)

reservation_lifecycle = Lifecycle(
    field=Reservation.status,
    initial=ReservationStatus.NONE,
    transitions=[
        Transition(ReservationStatus.NONE, ReservationStatus.RESERVED),
        Transition(ReservationStatus.RESERVED,
                   [ReservationStatus.RELEASED, ReservationStatus.CONSUMED]),
    ],
    terminal=[ReservationStatus.RELEASED, ReservationStatus.CONSUMED],
)

payment_lifecycle = Lifecycle(
    field=Payment.status,
    initial=PaymentStatus.NONE,
    transitions=[
        Transition(PaymentStatus.NONE, [PaymentStatus.AUTHORIZED, PaymentStatus.FAILED]),
        Transition(PaymentStatus.AUTHORIZED,
                   [PaymentStatus.CAPTURED, PaymentStatus.REFUNDED]),
        Transition(PaymentStatus.CAPTURED, PaymentStatus.REFUNDED),
    ],
    terminal=[PaymentStatus.FAILED, PaymentStatus.REFUNDED],
)

shipment_lifecycle = Lifecycle(
    field=Shipment.status,
    initial=ShipmentStatus.NONE,
    transitions=[
        Transition(ShipmentStatus.NONE, ShipmentStatus.DISPATCHED),
        Transition(ShipmentStatus.DISPATCHED,
                   [ShipmentStatus.DELIVERED, ShipmentStatus.LOST]),
    ],
    terminal=[ShipmentStatus.DELIVERED, ShipmentStatus.LOST],
)
