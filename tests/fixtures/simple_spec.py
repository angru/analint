from enum import StrEnum

from analint import Action, Entity, Expect, Scenario, Spec


class ItemStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Item(Entity):
    status: ItemStatus = ItemStatus.ACTIVE
    price: float
    stock: int


class Budget(Entity):
    amount: float


buy = Action(
    id="buy",
    name="Buy item",
    pre=[
        Item.price > 0,
        Budget.amount >= Item.price,
    ],
)

sc_ok = Scenario(
    id="buy/ok",
    name="Successful purchase",
    action=buy,
    given=[
        Item(price=10.0, stock=5),
        Budget(amount=20.0),
    ],
    expected=Expect.PASS,
)

spec = Spec(
    id="simple",
    name="Simple Spec",
    entities=[Item, Budget],
    actions=[buy],
    scenarios=[sc_ok],
)
