"""M5 partner increment alone, for the Quint/TLC cross-check (research/34 §8 B2).

The partner contract plus the client's security-code actions (a status change
and a reward withdrawal each spend a fresh code). The client is registered,
active and otherwise unchanged, so the reachable graph is the increment's own
(times the three regions).
"""

from examples.broker.domain import Client, Onboarding
from examples.broker.profile import code_expires, request_code, sc_code_expires, sc_code_is_issued

from analint import Initial, Spec

from . import base  # noqa: F401 — names the baseline objects (base.py docstring)
from .partners import Partner, Referral, RewardWallet, partners

spec = Spec(
    id="broker_m5_partners",
    name="Broker M5: partner increment alone",
    imports=[partners],
    actions=[request_code, code_expires],
    scenarios=[sc_code_is_issued, sc_code_expires],
    initial=Initial(
        vary=[Client.region],
        given=[Client(onboarding=Onboarding.CONTACTS), Partner(), Referral(), RewardWallet()],
    ),
    max_states=200_000,
)
