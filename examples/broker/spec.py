"""A generic retail broker, composed from one contract per business process.

See README.md: the model is a neutral composite of common industry practice
built as a scaling benchmark (research/34 §6).
"""

from analint import Absent, DeadActions, Initial, Spec

from .accounts import trading_accounts
from .domain import BUDGET, Client, accounts
from .payments import payments
from .profile import profile

# The canonical model starts from every region (some gate deposits or real
# trading on full verification), with no trading account opened yet.
initial = Initial(vary=[Client.region], given=[Absent(accounts["main"])])

# P11: every action can fire in some reachable state of the composed model
every_action_is_usable = DeadActions(max_states=BUDGET)

spec = Spec(
    id="broker",
    name="Generic retail broker",
    version="0.1.0",
    description="Client verification, trading accounts and payments as separate "
    "contracts; a scaling benchmark for independent and coupled processes.",
    imports=[profile, trading_accounts, payments],
    queries=[every_action_is_usable],
    initial=initial,
    max_states=BUDGET,
)
