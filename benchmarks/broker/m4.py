"""M4 entry: M3 cash ledger plus finite risk accounts and settlement buckets."""

from examples.broker.domain import Client, accounts

from analint import Absent, DeadActions, Initial, Spec

from .base import cash_payments, client_profile, trading_accounts
from .domain import BENCH_BUDGET, orders, risk_accounts
from .risk import risk

every_action_is_usable = DeadActions(max_states=BENCH_BUDGET)
spec = Spec(
    id="broker_m4",
    name="Broker M4: risk",
    imports=[client_profile, trading_accounts, cash_payments, risk],
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
