"""The client profile (M1) composed with the partner increment, for the
Quint/TLC cross-check (research/34 §8 B2). Their coupling is the shared
one-time security code: the profile issues it, partner status changes and
reward withdrawals spend it.
"""

from examples.broker.domain import Client

from analint import Initial, Spec

from .base import client_profile
from .partners import partners

spec = Spec(
    id="broker_m5_profile_partners",
    name="Broker M5: client profile with partners",
    imports=[client_profile, partners],
    initial=Initial(vary=[Client.region]),
    max_states=200_000,
)
