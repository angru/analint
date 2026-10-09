"""M5 entry: add introducing-partner restrictions and accrued rewards."""

from examples.broker.domain import Client, accounts

from analint import Absent, DeadActions, Initial, Spec

from .base import cash_payments, client_profile, trading_accounts
from .domain import BENCH_BUDGET, orders, risk_accounts
from .partners import partners
from .risk import risk

every_action_is_usable = DeadActions(max_states=BENCH_BUDGET)
spec = Spec(
    id="broker_m5",
    name="Broker M5: partners",
    imports=[client_profile, trading_accounts, cash_payments, risk, partners],
    initial=Initial(
        vary=[Client.region],
        given=[
            Absent(accounts["main"]),
            Absent(risk_accounts["primary"]),
            Absent(risk_accounts["secondary"]),
            Absent(orders["first"]),
            Absent(orders["second"]),
        ],
    ),
    queries=[every_action_is_usable],
    max_states=BENCH_BUDGET,
)
