"""The risk increment at M6 multiplicity (two concurrent risk accounts and
open orders), for the Quint/TLC cross-check (research/34 §8 B2)."""

from examples.broker.domain import Client, Onboarding

from analint import Absent, Initial, Spec

from .domain import Capacity, orders, risk_accounts
from .risk import risk

spec = Spec(
    id="broker_m6_risk",
    name="Broker M6: risk increment alone, two concurrent accounts and orders",
    imports=[risk],
    initial=Initial(
        vary=[Client.region],
        given=[
            Capacity(accounts=2, orders=2),
            Client(onboarding=Onboarding.CONTACTS),
            *(Absent(slot) for slot in risk_accounts),
            *(Absent(slot) for slot in orders),
        ],
    ),
    max_states=5_000_000,
)
