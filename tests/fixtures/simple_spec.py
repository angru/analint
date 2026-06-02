from enum import Enum
from analint import Entity, BusinessRule, UseCase, Scenario, Spec, Expect


class ItemStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Item(Entity):
    status: ItemStatus = ItemStatus.ACTIVE
    price: float
    stock: int


class Budget(Entity):
    amount: float


rule_price = BusinessRule(
    id="price-positive",
    name="Item price must be positive",
    expression=Item.price > 0,
)

rule_budget = BusinessRule(
    id="budget-covers",
    name="Budget must cover item price",
    expression=Budget.amount >= Item.price,
)

uc_buy = UseCase(
    id="buy",
    name="Buy item",
    entities=[Item, Budget],
    rules=[rule_price, rule_budget],
)

sc_ok = Scenario(
    id="buy/ok",
    name="Successful purchase",
    use_case=uc_buy,
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
    rules=[rule_price, rule_budget],
    use_cases=[uc_buy],
    scenarios=[sc_ok],
)
