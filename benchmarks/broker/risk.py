"""M4: equity-based leverage, margin call, ordered stop out and protection."""

from examples.broker.domain import AccountKind, Client, ClientStatus, Onboarding, Tier

from analint import (
    Absent,
    Action,
    And,
    Assert,
    Bound,
    Contract,
    Count,
    Create,
    Delete,
    Expect,
    Flow,
    ForAll,
    Implies,
    Invariant,
    Not,
    Or,
    Param,
    Present,
    Reachable,
    Scenario,
    Set,
)

from .domain import (
    BENCH_BUDGET,
    Capacity,
    EffectiveCap,
    Equity,
    History,
    Leverage,
    Margin,
    Market,
    Order,
    OrderStatus,
    Owner,
    Protection,
    RiskAccount,
    orders,
    risk_accounts,
)

acct = Param("acct", risk_accounts)
kind = Param("kind", AccountKind)
owner = Param("owner", Owner)
order = Param("order", orders)
profit = Param("profit", ge=-1, le=1)
equity = Param("equity", Equity)
margin = Param("margin", Margin)
account = Bound("risk_account", risk_accounts)
other = Bound("other_order", orders)
primary, secondary = risk_accounts["primary"], risk_accounts["secondary"]
first, second = orders["first"], orders["second"]

owner_matches = Or(
    And(acct == primary, owner == Owner.PRIMARY),
    And(acct == secondary, owner == Owner.SECONDARY),
)
open_orders = Count(other, other.status == OrderStatus.OPEN)
owned_open = Count(other, And(other.owner == owner, other.status == OrderStatus.OPEN))
active_client = Client.status == ClientStatus.ACTIVE

open_risk_account = Action(
    params=[acct, kind],
    pre=[
        active_client,
        Client.onboarding != Onboarding.NEW,
        Count(account, Present(account)) < Capacity.accounts,
    ],
    effect=[Create(acct, kind=kind)],
)
open_order = Action(
    params=[acct, owner, order, profit],
    where=[owner_matches],
    pre=[
        active_client,
        Present(acct),
        Not(Present(order)),
        acct.equity == Equity.SMALL,
        acct.margin == Margin.HEALTHY,
        acct.protection == Protection.NONE,
        open_orders < Capacity.orders,
    ],
    effect=[Create(order, owner=owner, profit=profit), Set(acct.fully_stopped, False)],
)
close_order = Action(
    params=[acct, owner, order],
    where=[owner_matches],
    pre=[
        active_client,
        Present(acct),
        Present(order),
        order.owner == owner,
        order.status == OrderStatus.OPEN,
        acct.margin != Margin.STOP,
    ],
    effect=[Set(order.status, OrderStatus.CLOSED), Set(History.completed_trade, True)],
)
reclaim_order = Action(
    params=[order],
    pre=[Present(order), order.status != OrderStatus.OPEN],
    effect=[Delete(order)],
)
choose_uncapped = Action(
    params=[acct],
    pre=[
        active_client,
        Present(acct),
        acct.equity == Equity.SMALL,
        History.completed_trade,
        Not(Market.high_margin),
    ],
    effect=[Set(acct.leverage, Leverage.UNCAPPED), Set(acct.effective_cap, EffectiveCap.HIGH)],
)
lower_cap = Action(
    params=[acct],
    pre=[Present(acct), acct.effective_cap == EffectiveCap.HIGH],
    effect=[Set(acct.effective_cap, EffectiveCap.LOW)],
)
start_high_margin = Action(
    pre=[Not(Market.high_margin), ForAll(account, account.effective_cap == EffectiveCap.LOW)],
    effect=[Set(Market.high_margin, True)],
)
end_high_margin = Action(pre=[Market.high_margin], effect=[Set(Market.high_margin, False)])
# A high-margin period starts after the risk service has lowered every cap.
# Selection (UNCAPPED eligibility) persists, while the effective cap stays LOW.
market_moves = Action(
    params=[acct, owner, equity, margin],
    where=[owner_matches, Implies(equity == Equity.NEGATIVE, margin == Margin.STOP)],
    pre=[
        Present(acct),
        owned_open > 0,
        acct.protection == Protection.NONE,
        Implies(equity == Equity.ZERO, margin != Margin.HEALTHY),
        Implies(And(acct.kind == AccountKind.CENT, equity == Equity.ZERO), margin == Margin.STOP),
    ],
    effect=[
        Set(acct.equity, equity),
        Set(acct.margin, margin),
        Set(acct.leverage, Leverage.CAPPED),
        Set(acct.effective_cap, EffectiveCap.LOW),
    ],
)
stop_worst_order = Action(
    params=[acct, owner, order],
    where=[owner_matches],
    pre=[
        Present(acct),
        Present(order),
        order.owner == owner,
        order.status == OrderStatus.OPEN,
        acct.margin == Margin.STOP,
        ForAll(
            other,
            Implies(
                And(other.owner == owner, other.status == OrderStatus.OPEN),
                order.profit <= other.profit,
            ),
        ),
    ],
    effect=[Set(order.status, OrderStatus.STOPPED)],
)
finish_negative_stop = Action(
    params=[acct, owner],
    where=[owner_matches],
    pre=[
        Present(acct),
        acct.equity == Equity.NEGATIVE,
        acct.margin == Margin.STOP,
        acct.protection == Protection.NONE,
        owned_open == 0,
    ],
    effect=[Set(acct.fully_stopped, True), Set(acct.protection, Protection.DUE)],
)
protect_negative_balance = Action(
    params=[acct, owner],
    where=[owner_matches],
    pre=[
        Present(acct),
        acct.fully_stopped,
        acct.equity == Equity.NEGATIVE,
        acct.protection == Protection.DUE,
        owned_open == 0,
    ],
    effect=[
        Set(acct.equity, Equity.ZERO),
        Set(acct.margin, Margin.HEALTHY),
        Set(acct.protection, Protection.PAID),
    ],
)
recapitalize = Action(
    params=[acct],
    pre=[active_client, Present(acct), acct.protection == Protection.PAID],
    effect=[
        Set(acct.equity, Equity.SMALL),
        Set(acct.protection, Protection.NONE),
        Set(acct.fully_stopped, False),
    ],
)

uncapped_requires_eligibility = Invariant(
    ForAll(
        account,
        Implies(
            account.leverage == Leverage.UNCAPPED,
            And(account.equity == Equity.SMALL, History.completed_trade),
        ),
    ),
)
high_margin_caps_leverage = Invariant(
    Implies(Market.high_margin, ForAll(account, account.effective_cap == EffectiveCap.LOW)),
)
protection_requires_full_stop = Invariant(
    ForAll(
        account,
        Implies(
            account.protection == Protection.PAID,
            And(account.fully_stopped, account.equity == Equity.ZERO),
        ),
    ),
)
portfolio_capacity_is_respected = Invariant(
    And(Count(account, Present(account)) <= Capacity.accounts, open_orders <= Capacity.orders),
)
verified_uncapped_during_high_margin = Reachable(
    And(
        Client.tier == Tier.FULL,
        Present(primary),
        primary.kind == AccountKind.PROFESSIONAL,
        primary.leverage == Leverage.UNCAPPED,
        Market.high_margin,
    ),
    max_states=BENCH_BUDGET,
)
negative_balance_can_be_protected = Reachable(
    And(Present(primary), primary.protection == Protection.PAID),
    max_states=BENCH_BUDGET,
)

_registered = Client(onboarding=Onboarding.CONTACTS)
_one_order = [
    Capacity(),
    History(),
    Market(),
    _registered,
    primary(),
    Absent(secondary),
    first(owner=Owner.PRIMARY),
    Absent(second),
]
sc_risk_account_opens = Scenario(
    action=open_risk_account.bind(acct=primary, kind=AccountKind.STANDARD),
    given=[Capacity(), _registered, Absent(primary), Absent(secondary)],
    then=[Present(primary)],
)
sc_uncapped_without_history_is_rejected = Scenario(
    action=choose_uncapped.bind(acct=primary),
    given=_one_order,
    expected=Expect.FAIL,
)
sc_completed_trade_unlocks_uncapped = Scenario(
    action=choose_uncapped.bind(acct=primary),
    given=[
        Capacity(),
        History(completed_trade=True),
        Market(),
        _registered,
        primary(),
        Absent(secondary),
        Absent(first),
        Absent(second),
    ],
    then=[primary.leverage == Leverage.UNCAPPED, primary.effective_cap == EffectiveCap.HIGH],
)
sc_high_margin_requires_lowered_caps = Scenario(
    action=start_high_margin,
    given=[
        Market(),
        History(completed_trade=True),
        primary(leverage=Leverage.UNCAPPED, effective_cap=EffectiveCap.HIGH),
        Absent(secondary),
    ],
    expected=Expect.FAIL,
)
sc_negative_market_enters_stop_out = Scenario(
    action=market_moves.bind(
        acct=primary, owner=Owner.PRIMARY, equity=Equity.NEGATIVE, margin=Margin.STOP
    ),
    given=_one_order,
    then=[primary.equity == Equity.NEGATIVE, primary.margin == Margin.STOP],
)
sc_stop_out_closes_an_order = Scenario(
    action=stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=first),
    given=[
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(owner=Owner.PRIMARY, profit=-1),
        Absent(second),
    ],
    then=[first.status == OrderStatus.STOPPED],
)
sc_protection_before_full_stop_is_rejected = Scenario(
    action=protect_negative_balance.bind(acct=primary, owner=Owner.PRIMARY),
    given=[
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(owner=Owner.PRIMARY),
        Absent(second),
    ],
    expected=Expect.FAIL,
)
sc_protection_resets_only_negative_equity = Scenario(
    action=protect_negative_balance.bind(acct=primary, owner=Owner.PRIMARY),
    given=[
        primary(
            equity=Equity.NEGATIVE,
            margin=Margin.STOP,
            fully_stopped=True,
            protection=Protection.DUE,
        ),
        Absent(secondary),
        Absent(first),
        Absent(second),
    ],
    then=[primary.equity == Equity.ZERO, primary.protection == Protection.PAID],
)

sc_order_opens_within_capacity = Scenario(
    action=open_order.bind(acct=primary, owner=Owner.PRIMARY, order=first, profit=0),
    given=[Capacity(), _registered, primary(), Absent(secondary), Absent(first), Absent(second)],
    then=[Present(first), first.owner == Owner.PRIMARY],
)
sc_second_open_order_exceeds_capacity = Scenario(
    action=open_order.bind(acct=primary, owner=Owner.PRIMARY, order=second, profit=1),
    given=_one_order,
    expected=Expect.FAIL,
)
sc_close_order_records_history = Scenario(
    action=close_order.bind(acct=primary, owner=Owner.PRIMARY, order=first),
    given=_one_order,
    then=[first.status == OrderStatus.CLOSED, History.completed_trade],
)
sc_closed_order_is_reclaimed = Scenario(
    action=reclaim_order.bind(order=first),
    given=[first(status=OrderStatus.CLOSED), Absent(second)],
    then=[Not(Present(first))],
)
sc_prepare_high_margin_lowers_effective_cap = Scenario(
    action=lower_cap.bind(acct=primary),
    given=[
        Market(),
        History(completed_trade=True),
        primary(leverage=Leverage.UNCAPPED, effective_cap=EffectiveCap.HIGH),
        Absent(secondary),
    ],
    then=[primary.effective_cap == EffectiveCap.LOW, primary.leverage == Leverage.UNCAPPED],
)
sc_high_margin_ends = Scenario(
    action=end_high_margin,
    given=[Market(high_margin=True), primary(), Absent(secondary)],
    then=[Not(Market.high_margin)],
)
sc_last_stop_makes_protection_due = Scenario(
    action=finish_negative_stop.bind(acct=primary, owner=Owner.PRIMARY),
    given=[
        primary(equity=Equity.NEGATIVE, margin=Margin.STOP),
        Absent(secondary),
        first(status=OrderStatus.STOPPED),
        Absent(second),
    ],
    then=[primary.fully_stopped, primary.protection == Protection.DUE],
)
sc_recapitalization_clears_protection = Scenario(
    action=recapitalize.bind(acct=primary),
    given=[
        _registered,
        primary(equity=Equity.ZERO, fully_stopped=True, protection=Protection.PAID),
        Absent(secondary),
        Absent(first),
        Absent(second),
    ],
    then=[primary.equity == Equity.SMALL, primary.protection == Protection.NONE],
)

negative_stop_and_protection = Flow(
    given=[
        Capacity(),
        History(),
        Market(),
        _registered,
        primary(),
        Absent(secondary),
        Absent(first),
        Absent(second),
    ],
    steps=[
        open_order.bind(acct=primary, owner=Owner.PRIMARY, order=first, profit=-1),
        market_moves.bind(
            acct=primary, owner=Owner.PRIMARY, equity=Equity.NEGATIVE, margin=Margin.STOP
        ),
        stop_worst_order.bind(acct=primary, owner=Owner.PRIMARY, order=first),
        finish_negative_stop.bind(acct=primary, owner=Owner.PRIMARY),
        protect_negative_balance.bind(acct=primary, owner=Owner.PRIMARY),
        Assert(And(primary.equity == Equity.ZERO, primary.protection == Protection.PAID)),
    ],
)

risk = Contract(
    id="risk",
    name="Leverage and risk settlement buckets",
    entities=[Client, Capacity, History, Market, RiskAccount, Order],
    scopes=[risk_accounts, orders],
    actions=[
        open_risk_account,
        open_order,
        close_order,
        reclaim_order,
        choose_uncapped,
        lower_cap,
        start_high_margin,
        end_high_margin,
        market_moves,
        stop_worst_order,
        finish_negative_stop,
        protect_negative_balance,
        recapitalize,
    ],
    invariants=[
        uncapped_requires_eligibility,
        high_margin_caps_leverage,
        protection_requires_full_stop,
        portfolio_capacity_is_respected,
    ],
    queries=[verified_uncapped_during_high_margin, negative_balance_can_be_protected],
    flows=[negative_stop_and_protection],
    scenarios=[
        sc_risk_account_opens,
        sc_uncapped_without_history_is_rejected,
        sc_completed_trade_unlocks_uncapped,
        sc_high_margin_requires_lowered_caps,
        sc_negative_market_enters_stop_out,
        sc_stop_out_closes_an_order,
        sc_protection_before_full_stop_is_rejected,
        sc_protection_resets_only_negative_equity,
        sc_order_opens_within_capacity,
        sc_second_open_order_exceeds_capacity,
        sc_close_order_records_history,
        sc_closed_order_is_reclaimed,
        sc_prepare_high_margin_lowers_effective_cap,
        sc_high_margin_ends,
        sc_last_stop_makes_protection_due,
        sc_recapitalization_clears_protection,
    ],
)
