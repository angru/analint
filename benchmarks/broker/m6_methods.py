"""M6 payment-method increment alone, for the Quint/TLC cross-check
(research/34 §8 B2).

Two payment-method slots and their ledger, plus the client's security-code
actions (a payout spends a fresh code). The client sits at the LOW tier and is
otherwise unchanged, so in the deposits-gated region no method can be funded.
"""

from examples.broker.domain import Client, Onboarding, Tier
from examples.broker.profile import code_expires, request_code, sc_code_expires, sc_code_is_issued

from analint import Absent, Initial, Spec

from . import base  # noqa: F401 — names the baseline objects (base.py docstring)
from .domain import Capacity
from .methods import MethodLedger, methods, payment_methods

spec = Spec(
    id="broker_m6_methods",
    name="Broker M6: payment-method increment alone",
    imports=[payment_methods],
    actions=[request_code, code_expires],
    scenarios=[sc_code_is_issued, sc_code_expires],
    initial=Initial(
        vary=[Client.region],
        given=[
            Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW),
            Capacity(accounts=2, orders=2, methods=2),
            MethodLedger(),
            *(Absent(slot) for slot in methods),
        ],
    ),
    max_states=500_000,
)
