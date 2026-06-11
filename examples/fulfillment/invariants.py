from analint import Bounds, Implies, Invariant
from .entities import (
    Order, OrderStatus, Payment, PaymentStatus, Reservation, ReservationStatus,
    Shipment, ShipmentStatus, Warehouse,
)

# ── World invariants ───────────────────────────────────────────────────────────

stock_not_negative = Invariant(
    Warehouse.stock >= 0,
    label="Warehouse stock can never go negative",
)

delivered_means_paid = Invariant(
    Implies(Order.status == OrderStatus.DELIVERED,
            Payment.status == PaymentStatus.CAPTURED),
    label="A delivered order is always a captured payment",
)

# ── Bounds (keep the state space finite) ───────────────────────────────────────

stock_bounds = Bounds(Warehouse.stock, 0, 2)

# ── Reusable predicates ────────────────────────────────────────────────────────

order_placed      = Order.status == OrderStatus.PLACED
order_confirmed   = Order.status == OrderStatus.CONFIRMED
order_shipped     = Order.status == OrderStatus.SHIPPED
order_cancelled   = Order.status == OrderStatus.CANCELLED
nothing_reserved  = Reservation.status == ReservationStatus.NONE
stock_reserved    = Reservation.status == ReservationStatus.RESERVED
payment_missing   = Payment.status == PaymentStatus.NONE
payment_authorized = Payment.status == PaymentStatus.AUTHORIZED
payment_captured  = Payment.status == PaymentStatus.CAPTURED
not_shipped_yet   = Shipment.status == ShipmentStatus.NONE
shipment_on_road  = Shipment.status == ShipmentStatus.DISPATCHED
shipment_lost     = Shipment.status == ShipmentStatus.LOST
