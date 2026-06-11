from analint import Event


class StockReserved(Event):
    order_id: str


class PaymentAuthorized(Event):
    order_id: str
    amount: float


class PaymentFailed(Event):
    order_id: str


class PaymentCaptured(Event):
    order_id: str
    amount: float


class ShipmentLost(Event):
    order_id: str
