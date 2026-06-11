from enum import StrEnum

from analint import Entity, Field, Lifecycle, Transition


class OrderStatus(StrEnum):
    PLACED    = "placed"
    CONFIRMED = "confirmed"
    SHIPPED   = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ReservationStatus(StrEnum):
    NONE     = "none"
    RESERVED = "reserved"
    RELEASED = "released"   # stock returned after a failure/cancellation
    CONSUMED = "consumed"   # goods left the warehouse


class PaymentStatus(StrEnum):
    NONE       = "none"
    AUTHORIZED = "authorized"
    FAILED     = "failed"
    CAPTURED   = "captured"
    REFUNDED   = "refunded"


class ShipmentStatus(StrEnum):
    NONE       = "none"
    DISPATCHED = "dispatched"
    DELIVERED  = "delivered"
    LOST       = "lost"


class Order(Entity):
    id: str = "order-1"
    qty: int = 1
    total: float = 100.0
    status: OrderStatus = Lifecycle(
        initial=OrderStatus.PLACED,
        transitions=[
            Transition(OrderStatus.PLACED, [OrderStatus.CONFIRMED, OrderStatus.CANCELLED]),
            Transition(OrderStatus.CONFIRMED, [OrderStatus.SHIPPED, OrderStatus.CANCELLED]),
            Transition(OrderStatus.SHIPPED, [OrderStatus.DELIVERED, OrderStatus.CANCELLED]),
        ],
        terminal=[OrderStatus.DELIVERED, OrderStatus.CANCELLED],
    )


class Warehouse(Entity):
    # Starts empty so the out-of-stock branch is reachable. Capacity is two.
    stock: int = Field(0, ge=0, le=2)


class Reservation(Entity):
    status: ReservationStatus = Lifecycle(
        initial=ReservationStatus.NONE,
        transitions=[
            Transition(ReservationStatus.NONE, [ReservationStatus.RESERVED]),
            Transition(
                ReservationStatus.RESERVED,
                [ReservationStatus.RELEASED, ReservationStatus.CONSUMED],
            ),
        ],
        terminal=[ReservationStatus.RELEASED, ReservationStatus.CONSUMED],
    )


class Payment(Entity):
    status: PaymentStatus = Lifecycle(
        initial=PaymentStatus.NONE,
        transitions=[
            Transition(PaymentStatus.NONE, [PaymentStatus.AUTHORIZED, PaymentStatus.FAILED]),
            Transition(
                PaymentStatus.AUTHORIZED,
                [PaymentStatus.CAPTURED, PaymentStatus.REFUNDED],
            ),
            Transition(PaymentStatus.CAPTURED, [PaymentStatus.REFUNDED]),
        ],
        terminal=[PaymentStatus.FAILED, PaymentStatus.REFUNDED],
    )


class Shipment(Entity):
    status: ShipmentStatus = Lifecycle(
        initial=ShipmentStatus.NONE,
        transitions=[
            Transition(ShipmentStatus.NONE, [ShipmentStatus.DISPATCHED]),
            Transition(
                ShipmentStatus.DISPATCHED,
                [ShipmentStatus.DELIVERED, ShipmentStatus.LOST],
            ),
        ],
        terminal=[ShipmentStatus.DELIVERED, ShipmentStatus.LOST],
    )
