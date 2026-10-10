"""M4 risk increment alone, for the Quint/TLC cross-check (research/34 §8 B2).

The client is registered and active and nothing changes it, so the reachable
graph is the risk increment's own (times the three regions). Both analint and
TLC finish it, unlike the full M4 product with the M3 cash ledger. Entities and
scopes follow from the risk contract by reference closure (research/35 R2).
"""

from examples.broker.domain import Client, Onboarding

from analint import Absent, Initial, Spec

from .domain import orders, risk_accounts
from .risk import risk

spec = Spec(
    id="broker_m4_risk",
    name="Broker M4: risk increment alone",
    imports=[risk],
    initial=Initial(
        vary=[Client.region],
        given=[
            Client(onboarding=Onboarding.CONTACTS),
            *(Absent(slot) for slot in risk_accounts),
            *(Absent(slot) for slot in orders),
        ],
    ),
    max_states=200_000,
)
