from analint import Entity, BusinessRule, UseCase, Scenario, Spec, Expect


class Item(Entity):
    price: float


class Budget(Entity):
    amount: float


class Phantom(Entity):
    value: float


rule_ok = BusinessRule(
    id="price-positive",
    name="Price must be positive",
    expression=Item.price > 0,
)

# Rule references Phantom entity which is NOT in spec.entities
rule_phantom = BusinessRule(
    id="phantom-rule",
    name="Phantom rule",
    expression=Phantom.value > 0,
)

uc_buy = UseCase(
    id="buy",
    name="Buy",
    entities=[Item, Budget],
    rules=[rule_ok, rule_phantom],
)

sc_missing_entity = Scenario(
    id="buy/missing",
    name="Budget missing from given",
    use_case=uc_buy,
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
    rules=[rule_ok, rule_phantom],
    use_cases=[uc_buy],
    scenarios=[sc_missing_entity],
)
