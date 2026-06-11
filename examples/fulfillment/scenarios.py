from analint import Assert, Expect, Scenario

from .actions import (
    authorize_payment,
    cancel_by_customer,
    capture_payment,
    close_lost_order,
    compensate_failed_payment,
    confirm_delivery,
    confirm_order,
    decline_payment,
    dispatch,
    refund_after_cancel,
    refund_lost,
    reject_out_of_stock,
    release_after_cancel,
    report_lost,
    reserve_stock,
    supplier_restock,
)
from .entities import (
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


def _world(
    order=OrderStatus.PLACED,
    stock=1,
    res=ReservationStatus.NONE,
    pay=PaymentStatus.NONE,
    ship=ShipmentStatus.NONE,
):
    return [
        Order(status=order),
        Warehouse(stock=stock),
        Reservation(status=res),
        Payment(status=pay),
        Shipment(status=ship),
    ]


sc_restock = Scenario(
    name="Supplier tops up the shelf",
    action=supplier_restock,
    given=_world(stock=0),
    then=[Assert(Warehouse.stock == 1)],
)

sc_reserve = Scenario(
    name="Goods reserved, stock drops",
    action=reserve_stock,
    given=_world(stock=1),
    then=[Assert(Reservation.status == ReservationStatus.RESERVED), Assert(Warehouse.stock == 0)],
)

sc_reject = Scenario(
    name="Empty shelf rejects the order",
    action=reject_out_of_stock,
    given=_world(stock=0),
    then=[Assert(Order.status == OrderStatus.CANCELLED)],
)

sc_reserve_needs_stock = Scenario(
    name="Cannot reserve from an empty shelf",
    action=reserve_stock,
    given=_world(stock=0),
    expected=Expect.FAIL,
)

sc_authorize = Scenario(
    name="Payment authorized after reservation",
    action=authorize_payment,
    given=_world(res=ReservationStatus.RESERVED),
    then=[Assert(Payment.status == PaymentStatus.AUTHORIZED)],
)

sc_decline = Scenario(
    name="Provider declines the payment",
    action=decline_payment,
    given=_world(res=ReservationStatus.RESERVED),
    then=[Assert(Payment.status == PaymentStatus.FAILED)],
)

sc_compensate_failed = Scenario(
    name="Failed payment: order cancelled, stock returns",
    action=compensate_failed_payment,
    given=_world(res=ReservationStatus.RESERVED, pay=PaymentStatus.FAILED, stock=0),
    then=[
        Assert(Order.status == OrderStatus.CANCELLED),
        Assert(Reservation.status == ReservationStatus.RELEASED),
        Assert(Warehouse.stock == 1),
    ],
)

sc_confirm = Scenario(
    name="Order confirmed once authorized",
    action=confirm_order,
    given=_world(res=ReservationStatus.RESERVED, pay=PaymentStatus.AUTHORIZED),
    then=[Assert(Order.status == OrderStatus.CONFIRMED)],
)

sc_capture = Scenario(
    name="Payment captured for a confirmed order",
    action=capture_payment,
    given=_world(
        order=OrderStatus.CONFIRMED, res=ReservationStatus.RESERVED, pay=PaymentStatus.AUTHORIZED
    ),
    then=[Assert(Payment.status == PaymentStatus.CAPTURED)],
)

sc_cancel = Scenario(
    name="Customer cancels before dispatch",
    action=cancel_by_customer,
    given=_world(
        order=OrderStatus.CONFIRMED, res=ReservationStatus.RESERVED, pay=PaymentStatus.AUTHORIZED
    ),
    then=[Assert(Order.status == OrderStatus.CANCELLED)],
)

sc_cancel_window_closed = Scenario(
    name="No cancellation after the payment is captured",
    action=cancel_by_customer,
    given=_world(
        order=OrderStatus.CONFIRMED, res=ReservationStatus.RESERVED, pay=PaymentStatus.CAPTURED
    ),
    expected=Expect.FAIL,
)

sc_refund = Scenario(
    name="Cancelled order gets the refund",
    action=refund_after_cancel,
    given=_world(
        order=OrderStatus.CANCELLED, res=ReservationStatus.RESERVED, pay=PaymentStatus.AUTHORIZED
    ),
    then=[Assert(Payment.status == PaymentStatus.REFUNDED)],
)

sc_release = Scenario(
    name="Cancelled order returns goods to the shelf",
    action=release_after_cancel,
    given=_world(order=OrderStatus.CANCELLED, res=ReservationStatus.RESERVED, stock=0),
    then=[Assert(Reservation.status == ReservationStatus.RELEASED), Assert(Warehouse.stock == 1)],
)

sc_dispatch = Scenario(
    name="Captured payment releases the shipment",
    action=dispatch,
    given=_world(
        order=OrderStatus.CONFIRMED, res=ReservationStatus.RESERVED, pay=PaymentStatus.CAPTURED
    ),
    then=[
        Assert(Shipment.status == ShipmentStatus.DISPATCHED),
        Assert(Order.status == OrderStatus.SHIPPED),
        Assert(Reservation.status == ReservationStatus.CONSUMED),
    ],
)

sc_delivery = Scenario(
    name="Shipment delivered",
    action=confirm_delivery,
    given=_world(
        order=OrderStatus.SHIPPED,
        res=ReservationStatus.CONSUMED,
        pay=PaymentStatus.CAPTURED,
        ship=ShipmentStatus.DISPATCHED,
    ),
    then=[Assert(Order.status == OrderStatus.DELIVERED)],
)

sc_lost = Scenario(
    name="Carrier loses the shipment",
    action=report_lost,
    given=_world(
        order=OrderStatus.SHIPPED,
        res=ReservationStatus.CONSUMED,
        pay=PaymentStatus.CAPTURED,
        ship=ShipmentStatus.DISPATCHED,
    ),
    then=[Assert(Shipment.status == ShipmentStatus.LOST)],
)

sc_refund_lost = Scenario(
    name="Lost shipment is refunded",
    action=refund_lost,
    given=_world(
        order=OrderStatus.SHIPPED,
        res=ReservationStatus.CONSUMED,
        pay=PaymentStatus.CAPTURED,
        ship=ShipmentStatus.LOST,
    ),
    then=[Assert(Payment.status == PaymentStatus.REFUNDED)],
)

sc_close_lost = Scenario(
    name="Lost order closes only after the refund",
    action=close_lost_order,
    given=_world(
        order=OrderStatus.SHIPPED,
        res=ReservationStatus.CONSUMED,
        pay=PaymentStatus.REFUNDED,
        ship=ShipmentStatus.LOST,
    ),
    then=[Assert(Order.status == OrderStatus.CANCELLED)],
)

sc_close_lost_needs_refund = Scenario(
    name="Cannot close a lost order before the refund",
    action=close_lost_order,
    given=_world(
        order=OrderStatus.SHIPPED,
        res=ReservationStatus.CONSUMED,
        pay=PaymentStatus.CAPTURED,
        ship=ShipmentStatus.LOST,
    ),
    expected=Expect.FAIL,
)
