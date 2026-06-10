from analint import Entity, Action, Scenario, Spec, Expect


class Item(Entity):
    price: float


class Budget(Entity):
    amount: float


class Phantom(Entity):
    value: float


# The action references Budget (omitted from given → warning)
# and Phantom (omitted from spec.entities → error).
buy = Action(
    id="buy",
    name="Buy",
    pre=[
        Item.price > 0,
        Budget.amount >= Item.price,
        Phantom.value > 0,
    ],
)

sc_missing_entity = Scenario(
    id="buy/missing",
    name="Budget missing from given",
    action=buy,
    given=[
        Item(price=10.0),
        # Budget intentionally omitted → structural warning
    ],
    expected=Expect.PASS,
)

spec = Spec(
    id="broken",
    name="Broken Spec",
    entities=[Item, Budget],   # Phantom intentionally omitted
    actions=[buy],
    scenarios=[sc_missing_entity],
)
