"""M6 witnesses and guards for two concurrent risk accounts and orders."""

from examples.broker.domain import Client, Onboarding

from analint import Absent, And, Bound, Contract, Count, Expect, Present, Reachable, Scenario

from .domain import (
    BENCH_BUDGET,
    Capacity,
    Equity,
    History,
    Margin,
    Market,
    OrderStatus,
    Owner,
    orders,
    risk_accounts,
)
from .risk import finish_negative_stop, open_order, stop_worst_order

primary, secondary = risk_accounts["primary"], risk_accounts["secondary"]
first, second = orders["first"], orders["second"]
account = Bound("account", risk_accounts)
order = Bound("order", orders)
two_accounts_and_orders_can_coexist = Reachable(
    And(Count(account, Present(account)) == 2, Count(order, order.status == OrderStatus.OPEN) == 2),
    max_states=BENCH_BUDGET,
)
sc_two_accounts_trade_concurrently = Scenario(
    action=open_order.bind(acct=secondary, owner=Owner.SECONDARY, order=second, profit=1),
    given=[
        Capacity(accounts=2, orders=2, methods=2),
        History(),
        Market(),
        Client(onboarding=Onboarding.CONTACTS),
        primary(),
        secondary(),
        first(owner=Owner.PRIMARY),
        Absent(second),
    ],
    then=[second.owner == Owner.SECONDARY, Count(order, order.status == OrderStatus.OPEN) == 2],
)
sc_stop_out_cannot_choose_the_better_order = Scenario(
    action=stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=second),
    given=[
        Capacity(orders=2),
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(owner=Owner.PRIMARY, profit=-1),
        second(owner=Owner.PRIMARY, profit=1),
    ],
    expected=Expect.FAIL,
)
sc_stop_out_selects_the_worst_order = Scenario(
    action=stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=first),
    given=[
        Capacity(orders=2),
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(owner=Owner.PRIMARY, profit=-1),
        second(owner=Owner.PRIMARY, profit=1),
    ],
    then=[first.status == OrderStatus.STOPPED, second.status == OrderStatus.OPEN],
)
sc_partial_stop_does_not_unlock_protection = Scenario(
    action=finish_negative_stop.bind(acct=primary, owner=Owner.PRIMARY),
    given=[
        Capacity(orders=2),
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(owner=Owner.PRIMARY, status=OrderStatus.STOPPED),
        second(owner=Owner.PRIMARY),
    ],
    expected=Expect.FAIL,
)
sc_other_accounts_losses_do_not_block_stop_out = Scenario(
    action=stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=first),
    given=[
        Capacity(accounts=2, orders=2),
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        secondary(),
        first(owner=Owner.PRIMARY, profit=1),
        second(owner=Owner.SECONDARY, profit=-1),
    ],
    then=[first.status == OrderStatus.STOPPED],
)
portfolio = Contract(
    id="portfolio",
    name="Multiplicity witnesses",
    queries=[two_accounts_and_orders_can_coexist],
    scenarios=[
        sc_two_accounts_trade_concurrently,
        sc_stop_out_cannot_choose_the_better_order,
        sc_stop_out_selects_the_worst_order,
        sc_partial_stop_does_not_unlock_protection,
        sc_other_accounts_losses_do_not_block_stop_out,
    ],
)
