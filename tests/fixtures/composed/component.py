from analint import Action, Add, Contract, Entity, Field, Invariant


class Ledger(Entity):
    balance: int = Field(0, ge=0, le=10)


balance_is_non_negative = Invariant(Ledger.balance >= 0)

credit = Action(
    id="credit",
    pre=[Ledger.balance < 10],
    effect=[Add(Ledger.balance, 1)],
)

reset_private = Action(
    id="reset-private",
    effect=[],
)

ledger_contract = Contract(
    id="ledger",
    name="Ledger API",
    version="1.0.0",
    entities=[Ledger],
    invariants=[balance_is_non_negative],
    actions=[credit],
)
