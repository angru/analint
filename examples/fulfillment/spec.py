from analint import Spec

# The entry point's import graph defines the spec.
from . import lifecycles, queries, scenarios  # noqa: F401

spec = Spec(
    id="fulfillment",
    name="Order Fulfillment Saga",
    version="1.0.0",
    description="A pure domain model of an order saga: reservation, payment, "
                "shipment, and a compensation for every failure — verified to "
                "never wedge",
)
