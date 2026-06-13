from analint import Scenario, Spec

from .component import Ledger, credit, ledger_contract

credit_once = Scenario(
    id="credit/once",
    action=credit,
    given=[Ledger(balance=0)],
)

spec = Spec(
    id="composed",
    name="Composed Spec",
    imports=[ledger_contract],
    scenarios=[credit_once],
)
