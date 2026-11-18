"""One system model reused for checkout, release and cross-flow properties."""

from analint import (
    Action,
    AlwaysHolds,
    Assert,
    Entity,
    Flow,
    Implies,
    Invariant,
    Not,
    Reachable,
    Scenario,
    Set,
    Spec,
)


class Order(Entity):
    reserved: bool = False
    shipped: bool = False


class Stock(Entity):
    available: bool = True


reserve = Action(
    id="reserve",
    pre=[Stock.available, Not(Order.reserved), Not(Order.shipped)],
    effect=[Set(Order.reserved, True), Set(Stock.available, False)],
)
ship = Action(
    id="ship",
    pre=[Order.reserved],
    effect=[Set(Order.shipped, True)],
)
release = Action(
    id="release",
    pre=[Order.reserved, Not(Order.shipped)],
    effect=[Set(Order.reserved, False), Set(Stock.available, True)],
)

checkout = Flow(
    id="checkout",
    given=[Order(), Stock()],
    steps=[reserve, ship, Assert(Order.shipped)],
)
release_reservation = Flow(
    id="release_reservation",
    given=[Order(reserved=True), Stock(available=False)],
    steps=[release, Assert(Not(Order.reserved))],
)
reservation_owns_stock = Invariant(
    Implies(Order.reserved, Not(Stock.available)),
    id="reservation_owns_stock",
)
shipment_keeps_reservation = AlwaysHolds(
    Implies(Order.shipped, Order.reserved),
    id="shipment_keeps_reservation",
)
can_ship = Reachable(Order.shipped, id="can_ship")

reserve_example = Scenario(
    id="reserve_example",
    action=reserve,
    given=[Order(), Stock()],
    tags=["checkout"],
)
ship_example = Scenario(
    id="ship_example",
    action=ship,
    given=[Order(reserved=True), Stock(available=False)],
    tags=["checkout"],
)
release_example = Scenario(
    id="release_example",
    action=release,
    given=[Order(reserved=True), Stock(available=False)],
    tags=["release"],
)

spec = Spec(
    id="shared_checks",
    name="Shared checkout and release model",
    actions=[reserve, ship, release],
    flows=[checkout, release_reservation],
    invariants=[reservation_owns_stock],
    queries=[shipment_keeps_reservation, can_ship],
    scenarios=[reserve_example, ship_example, release_example],
)
