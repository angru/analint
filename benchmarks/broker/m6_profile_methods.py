"""The client profile (M1) composed with the payment-method increment, for the
Quint/TLC cross-check (research/34 §8 B2). The verification tier and region
gate funding; the profile issues the code a payout spends.
"""

from examples.broker.domain import Client

from analint import Absent, Initial, Spec

from .base import client_profile
from .domain import Capacity
from .methods import MethodLedger, methods, payment_methods

spec = Spec(
    id="broker_m6_profile_methods",
    name="Broker M6: client profile with payment methods",
    imports=[client_profile, payment_methods],
    initial=Initial(
        vary=[Client.region],
        given=[
            Capacity(accounts=2, orders=2, methods=2),
            MethodLedger(),
            *(Absent(slot) for slot in methods),
        ],
    ),
    max_states=500_000,
)
