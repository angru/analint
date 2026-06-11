from enum import Enum
from analint import Entity


class OrderStatus(Enum):
    PLACED    = "placed"
    CONFIRMED = "confirmed"
    SHIPPED   = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ReservationStatus(Enum):
    NONE     = "none"
    RESERVED = "reserved"
    RELEASED = "released"   # stock returned after a failure/cancellation
    CONSUMED = "consumed"   # goods left the warehouse


class PaymentStatus(Enum):
    NONE       = "none"
    AUTHORIZED = "authorized"
    FAILED     = "failed"
    CAPTURED   = "captured"
    REFUNDED   = "refunded"


class ShipmentStatus(Enum):
    NONE       = "none"
    DISPATCHED = "dispatched"
    DELIVERED  = "delivered"
    LOST       = "lost"


class Order(Entity):
    id: str = "order-1"
    qty: int = 1
    total: float = 100.0
    status: OrderStatus = OrderStatus.PLACED


class Warehouse(Entity):
    stock: int = 0          # starts empty: the out-of-stock branch is reachable


class Reservation(Entity):
    status: ReservationStatus = ReservationStatus.NONE


class Payment(Entity):
    status: PaymentStatus = PaymentStatus.NONE


class Shipment(Entity):
    status: ShipmentStatus = ShipmentStatus.NONE
