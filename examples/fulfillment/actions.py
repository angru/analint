"""The fulfillment saga as domain actions.

Branching (payment succeeds / fails, shipment arrives / gets lost) is two
actions with the same precondition — the reachability engine explores both.
Every failure has a compensating action; the NoDeadEnd query in queries.py
proves the process can never wedge.
"""
from analint import Action, Add, Set, Subtract
from .entities import (
    Order, OrderStatus, Payment, PaymentStatus, Reservation, ReservationStatus,
    Shipment, ShipmentStatus, Warehouse,
)
from .events import (
    PaymentAuthorized, PaymentCaptured, PaymentFailed, ShipmentLost, StockReserved,
)
from .invariants import (
    nothing_reserved, not_shipped_yet, order_cancelled, order_confirmed,
    order_placed, order_shipped, payment_authorized, payment_captured,
    payment_missing, shipment_lost, shipment_on_road, stock_reserved,
)

# ── Stock ──────────────────────────────────────────────────────────────────────

# The shelf capacity is 2 and a reserved unit may come back as a return, so
# the supplier only refills an empty shelf. (The first version said
# `stock < 2` — and the NoDeadEnd query found a wedge: the supplier could
# fill the shelf while a payment was failing, leaving no room for the
# compensation to return the reserved unit.)
supplier_restock = Action(
    name="Supplier delivers stock",
    pre=[Warehouse.stock < 1],
    effect=[Add(Warehouse.stock, 1)],
)

reserve_stock = Action(
    name="Reserve goods for the order",
    pre=[order_placed, nothing_reserved, Warehouse.stock >= Order.qty],
    effect=[Set(Reservation.status, ReservationStatus.RESERVED),
            Subtract(Warehouse.stock, Order.qty)],
    emits=[StockReserved(order_id=Order.id)],
)

reject_out_of_stock = Action(
    name="Reject the order: nothing to reserve",
    pre=[order_placed, nothing_reserved, Warehouse.stock < Order.qty],
    effect=[Set(Order.status, OrderStatus.CANCELLED)],
)

# ── Payment ────────────────────────────────────────────────────────────────────

authorize_payment = Action(
    name="Authorize payment",
    on=StockReserved,
    pre=[order_placed, stock_reserved, payment_missing],
    effect=[Set(Payment.status, PaymentStatus.AUTHORIZED)],
    emits=[PaymentAuthorized(order_id=Order.id, amount=Order.total)],
)

decline_payment = Action(
    name="Payment declined by the provider",
    on=StockReserved,
    pre=[order_placed, stock_reserved, payment_missing],
    effect=[Set(Payment.status, PaymentStatus.FAILED)],
    emits=[PaymentFailed(order_id=Order.id)],
)

compensate_failed_payment = Action(
    name="Compensation: failed payment cancels the order, stock returns",
    on=PaymentFailed,
    pre=[order_placed, stock_reserved, Payment.status == PaymentStatus.FAILED],
    effect=[Set(Order.status, OrderStatus.CANCELLED),
            Set(Reservation.status, ReservationStatus.RELEASED),
            Add(Warehouse.stock, Order.qty)],
)

confirm_order = Action(
    name="Confirm the order",
    on=PaymentAuthorized,
    pre=[order_placed, stock_reserved, payment_authorized],
    effect=[Set(Order.status, OrderStatus.CONFIRMED)],
)

capture_payment = Action(
    name="Capture the authorized payment",
    pre=[order_confirmed, payment_authorized],
    effect=[Set(Payment.status, PaymentStatus.CAPTURED)],
    emits=[PaymentCaptured(order_id=Order.id, amount=Order.total)],
)

# ── Customer cancellation (the window closes at capture) ──────────────────────

cancel_by_customer = Action(
    name="Customer cancels before dispatch",
    pre=[order_confirmed, not_shipped_yet, payment_authorized],
    effect=[Set(Order.status, OrderStatus.CANCELLED)],
)

refund_after_cancel = Action(
    name="Compensation: refund the authorized payment",
    pre=[order_cancelled, payment_authorized],
    effect=[Set(Payment.status, PaymentStatus.REFUNDED)],
)

release_after_cancel = Action(
    name="Compensation: return reserved goods to the shelf",
    pre=[order_cancelled, stock_reserved],
    effect=[Set(Reservation.status, ReservationStatus.RELEASED),
            Add(Warehouse.stock, Order.qty)],
)

# ── Shipment ───────────────────────────────────────────────────────────────────

dispatch = Action(
    name="Dispatch the shipment",
    on=PaymentCaptured,
    pre=[order_confirmed, payment_captured, not_shipped_yet],
    effect=[Set(Shipment.status, ShipmentStatus.DISPATCHED),
            Set(Reservation.status, ReservationStatus.CONSUMED),
            Set(Order.status, OrderStatus.SHIPPED)],
)

confirm_delivery = Action(
    name="Confirm delivery",
    pre=[order_shipped, shipment_on_road],
    effect=[Set(Shipment.status, ShipmentStatus.DELIVERED),
            Set(Order.status, OrderStatus.DELIVERED)],
)

report_lost = Action(
    name="Carrier reports the shipment lost",
    pre=[order_shipped, shipment_on_road],
    effect=[Set(Shipment.status, ShipmentStatus.LOST)],
    emits=[ShipmentLost(order_id=Order.id)],
)

refund_lost = Action(
    name="Compensation: refund the captured payment for a lost shipment",
    on=ShipmentLost,
    pre=[shipment_lost, payment_captured],
    effect=[Set(Payment.status, PaymentStatus.REFUNDED)],
)

close_lost_order = Action(
    name="Close the lost order (only after the refund)",
    pre=[order_shipped, shipment_lost, Payment.status == PaymentStatus.REFUNDED],
    effect=[Set(Order.status, OrderStatus.CANCELLED)],
)
