"""M6 entry: two concurrent risk accounts, orders and payment methods."""

from examples.broker.domain import Client, accounts

from analint import Absent, DeadActions, Initial, Spec

from .base import cash_payments, client_profile, trading_accounts
from .domain import BENCH_BUDGET, Capacity, orders, risk_accounts
from .methods import methods, payment_methods
from .partners import partners
from .portfolio import portfolio
from .risk import risk

every_action_is_usable = DeadActions(max_states=BENCH_BUDGET)
spec = Spec(
    id="broker_m6",
    name="Broker M6: multiplicity",
    imports=[
        client_profile,
        trading_accounts,
        cash_payments,
        risk,
        partners,
        payment_methods,
        portfolio,
    ],
    initial=Initial(
        vary=[Client.region],
        given=[
            Capacity(accounts=2, orders=2, methods=2),
            Absent(accounts["main"]),
            Absent(risk_accounts["primary"]),
            Absent(risk_accounts["secondary"]),
            Absent(orders["first"]),
            Absent(orders["second"]),
            Absent(methods["card"]),
            Absent(methods["bank"]),
        ],
    ),
    queries=[every_action_is_usable],
    max_states=BENCH_BUDGET,
)
